#!/usr/bin/env python3
"""Basic smoke checks for the Vinyl Streamer stack."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vinyl_streamer import audio


def main() -> None:
    sources = audio.list_sources()
    sinks = audio.list_sinks()
    print(f"Sources: {len(sources)}")
    print(f"Sinks: {len(sinks)}")
    if not sources:
        raise SystemExit("No sources detected. Is pactl available?")
    if not sinks:
        raise SystemExit("No sinks detected. Is pactl available?")


if __name__ == "__main__":
    main()
