from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.bands import valid_bands

STATE_PATH = Path(os.environ.get("VINYL_STATE_PATH", str(Path(tempfile.gettempdir()) / "vinyl_streamer_state.json")))
logger = logging.getLogger(__name__)
EQ_UNIT = re.compile(r"vinyl-streamer-eq-([0-9a-f]{32})\.service")


@dataclass
class StreamState:
    source: str | None = None
    sink: str | None = None
    loopback_module: str | None = None
    raop_module: str | None = None
    latency_ms: int = 80
    running: bool = False
    eq_unit: str | None = None
    eq_sink: str | None = None
    eq_preset: str | None = None
    eq_bands: list[float] | None = None
    eq_cleanup: list[str] = field(default_factory=list)


def load_state() -> StreamState:
    if not STATE_PATH.exists():
        return StreamState()
    try:
        state = StreamState(**json.loads(STATE_PATH.read_text(encoding="utf-8")))
        for value in (state.source, state.sink, state.loopback_module, state.raop_module):
            if value is not None and not isinstance(value, str):
                raise ValueError("Invalid state identifier")
        if type(state.running) is not bool or type(state.latency_ms) is not int or not 40 <= state.latency_ms <= 500:
            raise ValueError("Invalid stream settings")
        if state.eq_unit is not None:
            match = EQ_UNIT.fullmatch(state.eq_unit)
            if not match or state.eq_sink != "vinyl_eq." + match.group(1) or state.eq_preset not in {"custom", "neutral", "warm", "bass", "clear", "voices"}:
                raise ValueError("Invalid equalizer identity")
        elif state.eq_sink is not None or state.eq_preset is not None:
            raise ValueError("Incomplete equalizer identity")
        # Keep old live-route metadata intact until the route is replaced.
        if state.eq_bands is not None and not valid_bands(state.eq_bands, (5, 6), limit=12):
            raise ValueError("Invalid equalizer bands")
        if state.eq_preset == "custom" and state.eq_bands is None:
            raise ValueError("Missing custom equalizer bands")
        if not isinstance(state.eq_cleanup, list) or any(not isinstance(unit, str) or not EQ_UNIT.fullmatch(unit) for unit in state.eq_cleanup):
            raise ValueError("Invalid equalizer cleanup list")
        return state
    except (OSError, ValueError, TypeError):
        logger.warning("Could not restore stream state", exc_info=True)
        return StreamState()


def atomic_write_json(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2))


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_state(state: StreamState) -> None:
    atomic_write_json(STATE_PATH, asdict(state))
