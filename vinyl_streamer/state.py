from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


STATE_PATH = Path("/tmp/vinyl_streamer_state.json")


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
        return StreamState(**data)
    except Exception:
        return StreamState()


def save_state(state: StreamState) -> None:
    STATE_PATH.write_text(json.dumps(asdict(state), indent=2))
