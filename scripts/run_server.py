#!/usr/bin/env python3
"""Run the Vinyl Streamer API server."""

from pathlib import Path
import sys

import uvicorn


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    uvicorn.run("vinyl_streamer.api:app", host="0.0.0.0", port=8000, reload=False)
