# Vinyl Streamer

Stream your Raspberry Pi's USB audio input to a Bose SoundTouch or another compatible AirPlay speaker.

Choose a speaker, start streaming, and control its volume or mute it. Audio input, buffer settings and technical details are under **Advanced**. A network-discovered speaker becomes selectable when the audio server exposes a usable output. The light/dark toggle follows your system setting until you choose a theme, then remembers your preference in this browser.

## Run

Requires **Python 3.11+**, a USB capture input, and PipeWire/PulseAudio with `pactl` and RAOP support. The Pi and speaker must be on the same network. Run the app as the user who owns the audio session.

```bash
python3 -m venv venv
./venv/bin/python -m pip install --no-cache-dir -r requirements.txt
./venv/bin/python scripts/run_server.py
```

Open **http://raspberrypi.local:8000/**.

For installation, updates, recovery and troubleshooting, see **[docs/setup.md](docs/setup.md)**. The installed user service is **`vinyl-streamer-app.service`** and the default installation folder is **`~/Vinyl-Streamer`**.

## Everyday commands on the Pi

```bash
systemctl --user status vinyl-streamer-app --no-pager
systemctl --user restart vinyl-streamer-app
journalctl --user -u vinyl-streamer-app -n 60 --no-pager
./venv/bin/python scripts/smoke_check.py
cat VERSION
```

The smoke check verifies audio devices; audible playback still needs a real speaker test. Stopping the API service leaves its PipeWire/PulseAudio loopback running. Use **Stop streaming** in the app to stop the audio.

## Project structure

```text
app/              API, stream control, discovery and static frontend
scripts/          Start server, check audio/UI and package a release
tests/            Automated tests using a simulated audio server
deploy/           Raspberry Pi user service
docs/setup.md     Installation, updates and troubleshooting
requirements.txt  Pinned runtime dependencies
VERSION           Release version
```

The frontend uses plain HTML, CSS and JavaScript. It needs no build step.

## Development

On Linux/the Pi, use `venv/bin/python`. On Windows, use `.venv/Scripts/python.exe` after creating the environment with `python -m venv .venv`.

```bash
./venv/bin/python -m pip install -r requirements-dev.txt
./venv/bin/python -m pytest -q
./venv/bin/python -m playwright install chromium
./venv/bin/python scripts/check_ui.py
```

The browser check also accepts `--browser /path/to/chrome` and saves screenshots under the ignored `artifacts/` folder. Browser tests simulate the API and do not control the Pi's audio.

## Git and releases

Work directly on `main` and make clear commits. The release version lives in `VERSION`; tags use `v0.1.0`, `v0.1.1`, etc.

For a release: update `VERSION`, run the tests and browser check, commit, and tag that commit. Build the upload package with:

```bash
./venv/bin/python scripts/package_release.py
```

This creates a verified `artifacts/vinyl-streamer-<version>.tar.gz` plus a `.sha256` file. The archive contains source, documentation, pinned dependencies and a file manifest, without Git metadata, virtual environments or caches. See [setup](docs/setup.md#update-an-existing-installation) for upload and update commands.

Runtime dependencies are pinned, including their dependencies, to make reinstalls predictable. Update them deliberately and rerun checks. Python itself, system audio packages and platform-specific wheels are supplied separately by the Pi/OS.
