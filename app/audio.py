from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class AudioItem:
    id: str
    name: str
    driver: str
    format: str
    state: str


@dataclass
class AudioModule:
    id: str
    name: str
    arguments: str


def _run(command: List[str]) -> str:
    try:
        result = subprocess.run(
            command, check=False, capture_output=True, text=True, timeout=5,
            env={**os.environ, "LC_ALL": "C"},
        )
    except FileNotFoundError as exc:
        raise RuntimeError("pactl ontbreekt. Installeer de PulseAudio-tools op de Pi.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("De audioserver reageert niet op tijd. Probeer opnieuw.") from exc
    except OSError as exc:
        raise RuntimeError(f"Het audiocommando kon niet worden uitgevoerd: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Command failed")
    return result.stdout.strip()


def list_sources() -> List[AudioItem]:
    output = _run(["pactl", "list", "short", "sources"])
    return _parse_items(output)


def list_sinks() -> List[AudioItem]:
    output = _run(["pactl", "list", "short", "sinks"])
    return _parse_items(output)


def is_airplay_sink(item: AudioItem) -> bool:
    return item.name.startswith(("raop_sink.", "raop_output.", "raop.")) or "raop" in item.driver.lower()


def _parse_items(output: str) -> List[AudioItem]:
    items: List[AudioItem] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            # Keep the sample specification (e.g. s16le 2ch 44100Hz) together.
            match = re.match(r"^(\S+)\s+(\S+)\s+(\S+)\s+(.+?)\s+(\S+)$", line.strip())
            if not match:
                continue
            parts = list(match.groups())
        if len(parts) != 5:
            continue
        items.append(
            AudioItem(
                id=parts[0],
                name=parts[1],
                driver=parts[2],
                format=parts[3],
                state=parts[4],
            )
        )
    return items


def find_raop_module() -> Optional[str]:
    for module in list_modules():
        if module.name == "module-raop-discover":
            return module.id
    return None


def list_modules() -> List[AudioModule]:
    output = _run(["pactl", "list", "short", "modules"])
    modules = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            modules.append(AudioModule(parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return modules


def is_stream_module(module: AudioModule, source: str | None, sink: str | None) -> bool:
    if module.name != "module-loopback" or not source or not sink:
        return False
    try:
        args = dict(arg.split("=", 1) for arg in shlex.split(module.arguments) if "=" in arg)
    except ValueError:
        return False
    return args.get("source") == source and args.get("sink") == sink


def ensure_raop_module() -> str:
    existing = find_raop_module()
    if existing:
        return existing
    return _run(["pactl", "load-module", "module-raop-discover"]).strip()


def unload_module(module_id: str) -> None:
    _run(["pactl", "unload-module", module_id])


def start_loopback(source: str, sink: str, latency_ms: int) -> str:
    return _run(
        [
            "pactl",
            "load-module",
            "module-loopback",
            f"source={source}",
            f"sink={sink}",
            f"latency_msec={latency_ms}",
            "source_dont_move=true",
            "sink_dont_move=true",
        ]
    )


def stop_loopback(module_id: str) -> None:
    unload_module(module_id)


def set_sink_volume(sink: str, volume: int) -> None:
    volume = max(0, min(volume, 150))
    _run(["pactl", "set-sink-volume", sink, f"{volume}%"])


def get_sink_volume(sink: str) -> int | None:
    output = _run(["pactl", "get-sink-volume", sink])
    for token in output.split():
        if token.endswith("%"):
            try:
                return int(token.strip("%"))
            except ValueError:
                continue
    return None


def set_sink_mute(sink: str, muted: bool) -> None:
    _run(["pactl", "set-sink-mute", sink, "1" if muted else "0"])


def get_sink_mute(sink: str) -> bool:
    # Boolean output is stable across locales when LC_ALL=C is supplied.
    output = _run(["pactl", "get-sink-mute", sink])
    return output.rsplit(":", 1)[-1].strip().lower() in {"yes", "true", "1"}


def pick_default_source(sources: List[AudioItem] | None = None) -> Optional[str]:
    if sources is None:
        sources = list_sources()
    candidates = [s for s in sources if not s.name.endswith(".monitor") and not s.name.startswith("auto_null")]
    return next((item.name for item in candidates if "usb" in item.name.lower()), None) or next((item.name for item in candidates), None)
