# Vinyl Streamer

Stream vinyl audio (USB capture) to Bose SoundTouch via AirPlay, with a simple web UI for device selection, volume, and connect/disconnect.

## Features
- AirPlay/RAOP streaming via PipeWire/PulseAudio.
- Web UI with status, connect/disconnect, and volume control.
- Manual refresh for input/output devices.

## Requirements
- Raspberry Pi 4 with a USB capture card.
- Bose SoundTouch on the same network.
- Python 3.9+.
- PipeWire or PulseAudio with `pactl` available.

## Quickstart
```bash
python -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python scripts/run_server.py
```

Open: `http://<pi-ip>:8000`

## Autostart (systemd)
Run the server automatically at boot with a systemd service. Prefer a path without spaces (e.g., a symlink).

```bash
ln -sfn "/home/pi/Vinyl Streamer" /home/pi/vinyl_streamer
```

Service example:
```ini
[Unit]
Description=Vinyl Streamer API
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=pi
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=PULSE_SERVER=unix:/run/user/1000/pulse/native
WorkingDirectory=/home/pi/vinyl_streamer
ExecStart=/home/pi/vinyl_streamer/venv/bin/python /home/pi/vinyl_streamer/scripts/run_server.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

## Troubleshooting
- Status: `systemctl status vinyl-streamer`
- Logs: `journalctl -u vinyl-streamer -f`

## Smoke check
```bash
./venv/bin/python scripts/smoke_check.py
```
