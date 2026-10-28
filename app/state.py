from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


STATE_PATH = Path(os.environ.get("VINYL_STATE_PATH", str(Path(tempfile.gettempdir()) / "vinyl_streamer_state.json")))
logger = logging.getLogger(__name__)


@dataclass
class StreamState:
    source: Optional[str] = None
    sink: Optional[str] = None
    loopback_module: Optional[str] = None
    raop_module: Optional[str] = None
    latency_ms: int = 80
    running: bool = False


def load_state() -> StreamState:
    if not STATE_PATH.exists():
        return StreamState()
    try:
        data = json.loads(STATE_PATH.read_text())
        state = StreamState(**data)
        for value in (state.source, state.sink, state.loopback_module, state.raop_module):
            if value is not None and not isinstance(value, str):
                raise ValueError("Invalid state identifier")
        if type(state.running) is not bool or type(state.latency_ms) is not int or not 40 <= state.latency_ms <= 500:
            raise ValueError("Invalid stream settings")
        return state
    except (OSError, ValueError, TypeError):
        logger.warning("Could not restore stream state", exc_info=True)
        return StreamState()


def save_state(state: StreamState) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=STATE_PATH.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(asdict(state), file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, STATE_PATH)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
