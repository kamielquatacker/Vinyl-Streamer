from __future__ import annotations

import re
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


def _run(command: List[str]) -> str:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Command failed")
    return result.stdout.strip()


def list_sources() -> List[AudioItem]:
    output = _run(["pactl", "list", "short", "sources"])
    return _parse_items(output)


def list_sinks() -> List[AudioItem]:
    output = _run(["pactl", "list", "short", "sinks"])
    return _parse_items(output)


def _parse_items(output: str) -> List[AudioItem]:
    items: List[AudioItem] = []
    for line in output.splitlines():
        parts = re.split(r"\s+", line)
        if len(parts) < 5:
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
    output = _run(["pactl", "list", "short", "modules"])
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1] == "module-raop-discover":
            return parts[0]
    return None


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


def pick_default_source() -> Optional[str]:
    sources = list_sources()
    for source in sources:
        if "usb" in source.name and "input" in source.name:
            return source.name
    return sources[0].name if sources else None
