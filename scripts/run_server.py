#!/usr/bin/env python3
"""Run the Vinyl Streamer API server."""

from pathlib import Path
import logging
import os
import sys

import uvicorn


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        "app.api:app", host=os.environ.get("VINYL_HOST", "0.0.0.0"),
        port=int(os.environ.get("VINYL_PORT", "8000")), reload=False, workers=1,
    )
