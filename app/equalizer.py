from __future__ import annotations

import json
import logging
import math
import cmath
from functools import lru_cache
import os
from pathlib import Path
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from uuid import uuid4

from app import audio
from app.bands import FREQUENCIES, migrate_bands, valid_bands
from app.state import atomic_write_json, atomic_write_text

logger = logging.getLogger(__name__)
PRESETS = {
    "custom": {"name": "Custom", "description": "Je eigen klankinstelling.", "gains": (0, 0, 0, 0, 0, 0)},
    "neutral": {"name": "Neutraal", "description": "Geen tooncorrectie.", "gains": (0, 0, 0, 0, 0, 0)},
    "warm": {"name": "Warm", "description": "Vol laag en duidelijk zachter hoog.", "gains": (3, 2, 1, 0, -1.5, -4)},
    "bass": {"name": "Meer bas", "description": "Een stevige boost voor de lage tonen.", "gains": (6, 4, 2, 0, -1, -2)},
    "clear": {"name": "Helder", "description": "Fris hoog en minder nadruk op het laag.", "gains": (-2, -1.5, -1, 0, 3, 2.5)},
    "voices": {"name": "Stemmen", "description": "Stemmen naar voren, met minder laag.", "gains": (-4, -2.5, -1, 3, 3, -2)},
}
SETTINGS_PATH = Path(os.environ.get(
    "VINYL_EQ_SETTINGS_PATH",
    str(Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "vinyl-streamer" / "equalizer.json"),
))
UNIT_PATTERN = re.compile(r"vinyl-streamer-eq-([0-9a-f]{32})\.service")


@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    preset: str = "neutral"
    bands: tuple[float, ...] = (0, 0, 0, 0, 0, 0)

    def __post_init__(self) -> None:
        if not valid_bands(self.bands):
            raise ValueError("Kies zes equaliserbanden tussen -10 en +10 dB.")
        object.__setattr__(self, "bands", tuple(self.bands))
        if type(self.enabled) is not bool or self.preset not in PRESETS:
            raise ValueError("Ongeldige equaliserinstelling.")

    @property
    def gains(self) -> tuple:
        return self.bands if self.preset == "custom" else PRESETS[self.preset]["gains"]


def load_settings() -> Settings:
    try:
        if SETTINGS_PATH.exists():
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if "bands" in data:
                data["bands"] = migrate_bands(data["bands"])
            return Settings(**data)
    except (OSError, ValueError, TypeError):
        logger.warning("Could not load equalizer preferences", exc_info=True)
    return Settings()


def save_settings(settings: Settings) -> None:
    atomic_write_json(SETTINGS_PATH, asdict(settings))


def new_unit() -> str:
    return f"vinyl-streamer-eq-{uuid4().hex}.service"


def processing_sink(unit: str) -> str:
    match = UNIT_PATTERN.fullmatch(unit)
    if match is None:
        raise ValueError("Ongeldige equaliser-identiteit.")
    return "vinyl_eq." + match.group(1)


def gains_for(preset: str, bands=None) -> tuple:
    return Settings(preset=preset, bands=bands if bands is not None else (0, 0, 0, 0, 0, 0)).gains


@lru_cache(maxsize=128)
def _headroom(gains: tuple) -> float:
    if max(gains) <= 0:
        return 0.0
    # RBJ peaking response, including overlapping bands.
    # https://www.w3.org/TR/audio-eq-cookbook/
    # Sample common audio rates; keep 0.2 dB margin above the measured peak.
    peak = 0.0
    for rate in (44100, 48000, 96000):
        coefficients = []
        for frequency, gain in zip(FREQUENCIES, gains):
            a = 10 ** (gain / 40)
            omega = 2 * math.pi * frequency / rate
            alpha = math.sin(omega) / (2 * 0.7)
            coefficients.append((1 + alpha*a, -2*math.cos(omega), 1-alpha*a,
                                 1+alpha/a, -2*math.cos(omega), 1-alpha/a))
        frequencies = [10 * (rate * 0.499 / 10) ** (index / 1023) for index in range(1024)]
        for frequency in frequencies + list(FREQUENCIES):
            z = cmath.exp(-2j * math.pi * frequency / rate)
            response = 1.0
            for b0, b1, b2, a0, a1, a2 in coefficients:
                response *= abs((b0+b1*z+b2*z*z)/(a0+a1*z+a2*z*z))
            peak = max(peak, 20 * math.log10(response))
    return -math.ceil((peak + 0.2) * 10 - 1e-8) / 10


def preamp_db(preset: str, bands=None) -> float:
    return _headroom(gains_for(preset, bands))


def filter_config(unit: str, target: str, preset: str, bands=None) -> dict:
    name = processing_sink(unit)
    nodes, links, inputs, outputs = [], [], [], []
    for channel in ("L", "R"):
        previous = f"preamp_{channel}"
        nodes.append({"type": "builtin", "name": previous, "label": "linear",
                      "control": {"Mult": 10 ** (preamp_db(preset, bands) / 20), "Add": 0.0}})
        inputs.append(previous + ":In")
        for index, (frequency, gain) in enumerate(zip(FREQUENCIES, gains_for(preset, bands))):
            current = f"band{index}_{channel}"
            nodes.append({"type": "builtin", "name": current, "label": "bq_peaking",
                          "control": {"Freq": frequency, "Q": 0.7, "Gain": gain}})
            links.append({"output": previous + ":Out", "input": current + ":In"})
            previous = current
        outputs.append(previous + ":Out")
    return {
        "context.properties": {"core.daemon": False, "log.level": 1},
        "context.spa-libs": {"audio.convert.*": "audioconvert/libspa-audioconvert",
                             "support.*": "support/libspa-support"},
        "context.modules": [
            {"name": "libpipewire-module-rt", "flags": ["ifexists", "nofail"]},
            {"name": "libpipewire-module-protocol-native"},
            {"name": "libpipewire-module-client-node"},
            {"name": "libpipewire-module-adapter"},
            {"name": "libpipewire-module-filter-chain", "args": {
                "node.description": "Vinyl Streamer equaliser", "media.name": "Vinyl Streamer EQ",
                "audio.channels": 2, "audio.position": ["FL", "FR"],
                "filter.graph": {"nodes": nodes, "links": links, "inputs": inputs, "outputs": outputs},
                "capture.props": {"node.name": name, "media.class": "Audio/Sink",
                                  "node.virtual": True, "priority.session": 0},
                "playback.props": {"node.name": name + ".output", "target.object": target,
                                   "node.passive": True, "node.dont-fallback": True,
                                   "node.dont-reconnect": True},
            }},
        ],
    }


def config_text(config: dict) -> str:
    # Native SPA syntax avoids parser differences between PipeWire releases.
    def value(item):
        if isinstance(item, dict):
            return "{ " + " ".join(json.dumps(key) + " = " + value(val) for key, val in item.items()) + " }"
        if isinstance(item, list):
            return "[ " + " ".join(value(val) for val in item) + " ]"
        return json.dumps(item)
    return "\n".join(json.dumps(key) + " = " + value(val) for key, val in config.items()) + "\n"


class EqualizerEngine:
    """Transient user services keep filter clients alive across API restarts."""

    def available(self) -> bool:
        return sys.platform.startswith("linux") and all(
            shutil.which(command) for command in ("pipewire", "systemd-run", "systemctl")
        )

    def runtime_dir(self) -> Path:
        base = os.environ.get("XDG_RUNTIME_DIR")
        if not base:
            raise RuntimeError("De gebruikerssessie ontbreekt (XDG_RUNTIME_DIR).")
        return Path(base) / "vinyl-streamer-eq"

    def config_path(self, unit: str) -> Path:
        processing_sink(unit)  # Validate before using a unit in a path or command.
        return self.runtime_dir() / (unit.removesuffix(".service") + ".conf")

    def start(self, unit: str, target: str, preset: str, bands=None) -> str:
        if not self.available():
            raise RuntimeError("Equaliser vereist PipeWire en een systemd-gebruikerssessie op de Pi.")
        version = audio._run(["pipewire", "--version"])
        match = re.search(r"Linked with libpipewire (\d+)\.(\d+)", version)
        if not match or tuple(map(int, match.groups())) < (1, 2):
            raise RuntimeError("Equaliser vereist PipeWire 1.2 of nieuwer.")
        path = self.config_path(unit)
        atomic_write_text(path, config_text(filter_config(unit, target, preset, bands)))
        # No PartOf= relation: stopping/restarting the API must not orphan or kill audio.
        audio._run(["systemd-run", "--user", "--quiet", "--collect", "--unit=" + unit,
                    "--property=Type=exec", "--property=TimeoutStopSec=3s",
                    "--", shutil.which("pipewire"), "-c", str(path)])
        name = processing_sink(unit)
        deadline = time.monotonic() + 5
        ready = 0
        while time.monotonic() < deadline:
            active = audio._run(["systemctl", "--user", "show", unit, "--property=ActiveState", "--value"])
            if active not in {"activating", "active"}:
                break
            ready = ready + 1 if active == "active" and any(item.name == name for item in audio.list_sinks()) else 0
            if ready >= 2:
                # Internal processing must not inherit a quiet default/remembered volume.
                # User volume remains on the physical speaker only.
                audio.set_sink_volume(name, 100)
                audio.set_sink_mute(name, False)
                return name
            time.sleep(0.1)
        raise RuntimeError("De equaliser kon niet starten. Controleer de PipeWire-filter-chain en de gebruikerslogs.")

    def stop(self, unit: str) -> None:
        path = self.config_path(unit)
        listed = audio._run(["systemctl", "--user", "list-units", "--all", "--no-legend", "--plain", "--full", unit])
        if listed.strip():
            command = audio._run(["systemctl", "--user", "show", unit, "--property=ExecStart", "--value"])
            if str(path) not in command:
                raise RuntimeError("De equaliser-service komt niet overeen met deze app; niet gestopt.")
            audio._run(["systemctl", "--user", "stop", unit])
        path.unlink(missing_ok=True)
