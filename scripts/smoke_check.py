#!/usr/bin/env python3
"""Basic smoke checks for the Vinyl Streamer stack."""

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import audio


def main() -> None:
    try:
        module_id = audio.ensure_raop_module()
        sources = [item for item in audio.list_sources() if not item.name.endswith(".monitor") and not item.name.startswith("auto_null")]
        deadline = time.monotonic() + 5
        while True:
            sinks = [item for item in audio.list_sinks() if audio.is_airplay_sink(item)]
            if sinks or time.monotonic() >= deadline:
                break
            time.sleep(0.25)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"RAOP discovery module: {module_id}")
    print(f"Audio inputs: {len(sources)}")
    print(f"AirPlay outputs: {len(sinks)}")
    for item in sources + sinks:
        print(f"  {item.name} [{item.state}]")
    if not sources:
        raise SystemExit("No audio inputs detected. Check the USB capture card.")
    if not sinks:
        raise SystemExit("No AirPlay output detected. Check the speaker, network and RAOP module.")
    print("Audio devices are available. Start streaming in the web UI to check audible playback.")


if __name__ == "__main__":
    main()
