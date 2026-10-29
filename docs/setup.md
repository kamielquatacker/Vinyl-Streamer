# Raspberry Pi setup

The installation folder is `~/Vinyl-Streamer`. The app runs as the user service `vinyl-streamer-app.service`, under the same user as PipeWire/PulseAudio. Examples use the SSH user `kamiel` and Pi address `192.168.129.204`; change these for another Pi.

## Prerequisites

- Raspberry Pi OS with Python **3.11+** and `venv`.
- A working USB capture input and compatible AirPlay/RAOP speaker.
- PipeWire with PulseAudio compatibility, or PulseAudio, with `pactl` and RAOP discovery support.
- Free disk space for a second environment during updates. About 1 GB free gives useful headroom.

On the Pi, as the audio-session user:

```bash
python3 --version
df -h /
pactl info
pactl list short sources
pactl list short sinks
```

If creating a virtual environment fails because `venv` is missing, install `python3-venv` using your OS package manager.

## Package and upload

On your development computer, from the repository root:

```bash
python scripts/package_release.py
```

On Windows PowerShell, upload the generated archive and its matching checksum (replace the version for later releases):

```powershell
scp .\artifacts\vinyl-streamer-0.1.0.tar.gz .\artifacts\vinyl-streamer-0.1.0.tar.gz.sha256 kamiel@192.168.129.204:~/
ssh kamiel@192.168.129.204
```

On the Pi, verify the upload **before extracting**:

```bash
cd "$HOME"
sha256sum -c vinyl-streamer-0.1.0.tar.gz.sha256
```

It must report `OK`. A failed upload to a full disk can leave a file with the correct name and size but invalid contents. Stop if the checksum fails and upload both files again.

## First installation

These commands assume `~/Vinyl-Streamer` does not already exist. If it does, use the update procedure below.

```bash
mkdir "$HOME/Vinyl-Streamer" &&
tar -xzf "$HOME/vinyl-streamer-0.1.0.tar.gz" -C "$HOME/Vinyl-Streamer"
```

Then install and check the app. Stop if any command fails.

```bash
cd "$HOME/Vinyl-Streamer"
python3 -m venv venv
./venv/bin/python -m pip install --no-cache-dir -r requirements.txt
./venv/bin/python -c "from app.api import app; print('Application loaded')"
./venv/bin/python scripts/smoke_check.py
```

The smoke check enables RAOP discovery if needed, waits up to five seconds for an output, and excludes monitor inputs. It does not start a stream or confirm audible playback.

Before starting the new service, stop and disable any older `vinyl-streamer.service` using its original scope: `sudo systemctl` for a system service, or `systemctl --user` for a user service. Keep its installation folder until the new version has been checked.

Install the user service:

```bash
mkdir -p "$HOME/.config/systemd/user"
cp deploy/vinyl-streamer-app.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
sudo loginctl enable-linger "$(id -un)"
systemctl --user enable --now vinyl-streamer-app.service
```

Lingering starts the user manager at boot and keeps it running after logout. Run only one API instance for this audio session. The service expects the environment at `~/Vinyl-Streamer/venv`; adjust its paths if you install elsewhere.

## Check the running version

```bash
systemctl --user status vinyl-streamer-app --no-pager
systemctl --user show vinyl-streamer-app -p MainPID -p WorkingDirectory -p ExecStart --no-pager
curl --fail http://127.0.0.1:8000/api/status
echo
cat "$HOME/Vinyl-Streamer/VERSION"
```

The working directory and command must point into `~/Vinyl-Streamer`. Open `http://raspberrypi.local:8000/`, refresh the browser and test **Stop streaming**, **Start streaming**, volume and mute. A healthy status is not proof of audible playback.

After first installation, a reboot is a useful check of automatic startup. The API service starts at boot; a fresh boot does not automatically start an audio stream.

## Update an existing installation

Build and upload a new archive and checksum as above. The example below uses `0.1.0`; change it to the version you are installing.

Unpack into a separate folder while the current app keeps running:

```bash
cd "$HOME"
sha256sum -c vinyl-streamer-0.1.0.tar.gz.sha256 &&
mkdir "$HOME/Vinyl-Streamer-next" &&
tar -xzf "$HOME/vinyl-streamer-0.1.0.tar.gz" -C "$HOME/Vinyl-Streamer-next"
```

Stop at any error. If `Vinyl-Streamer-next` or `Vinyl-Streamer-previous` already exists, inspect it first and move it to another backup name if you need to retain it.

Switch folders after verifying the archive. The previous installation, including its environment, is kept for rollback:

```bash
cd "$HOME"
test ! -e "$HOME/Vinyl-Streamer-previous" &&
systemctl --user stop vinyl-streamer-app &&
mv "$HOME/Vinyl-Streamer" "$HOME/Vinyl-Streamer-previous" &&
mv "$HOME/Vinyl-Streamer-next" "$HOME/Vinyl-Streamer"
```

Create the new environment at its final path, install dependencies and check the app. There is a short web-app interruption during this step. Stop at any error; use the rollback below if installation fails. The audio loopback may keep playing independently.

```bash
cd "$HOME/Vinyl-Streamer"
python3 -m venv venv &&
./venv/bin/python -m pip install --no-cache-dir -r requirements.txt &&
./venv/bin/python -c "from app.api import app; print('Application loaded')" &&
./venv/bin/python scripts/smoke_check.py
```

After all checks pass, refresh the service and start it:

```bash
cp deploy/vinyl-streamer-app.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user start vinyl-streamer-app
```

Repeat the running-version and playback checks. Once everything works, the previous folder can be removed manually to recover space.

### Roll back an update

These commands preserve the failed version as `~/Vinyl-Streamer-failed`. That destination must not already exist.

```bash
cd "$HOME"
test ! -e "$HOME/Vinyl-Streamer-failed" &&
test -d "$HOME/Vinyl-Streamer-previous" &&
systemctl --user stop vinyl-streamer-app &&
mv "$HOME/Vinyl-Streamer" "$HOME/Vinyl-Streamer-failed" &&
mv "$HOME/Vinyl-Streamer-previous" "$HOME/Vinyl-Streamer"

cd "$HOME/Vinyl-Streamer"
cp deploy/vinyl-streamer-app.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user start vinyl-streamer-app
```

For the original manual installation, its service file may still be named `deploy/vinyl-streamer.service`; in that case copy it to `~/.config/systemd/user/vinyl-streamer-app.service` instead.

## Equalizer presets

The **Geluid** panel has an on/off switch, five presets and **Custom** at the top of the list. Five sliders control 60 Hz, 250 Hz, 1 kHz, 4 kHz and 12 kHz, from -6 to +6 dB in 0.5 dB steps. Editing a preset automatically switches to Custom. Values are previewed while dragging and applied once you release the slider. Custom values survive switching presets and restarting the app. With the equalizer off, the original direct audio route is used. Enabling it requires **PipeWire 1.2+**, its built-in filter-chain module and the existing systemd user session. No additional Python dependencies or audio plugins are needed. PulseAudio-only installations retain direct streaming.

| Preset | Sound |
| --- | --- |
| Neutraal | No tone correction |
| Warm | Fuller bass, softer treble |
| Meer bas | More emphasis on low frequencies |
| Helder | More emphasis on detail |
| Stemmen | More emphasis on voices |

Each channel has five independent filters. The preamp now estimates the peak of the combined filter response at common sample rates, including overlapping bands, with a 0.2 dB margin and upward rounding to 0.1 dB. It no longer adds all positive band gains. Flat and cut-only curves get no additional attenuation; boosted curves can still sound quieter. The internal EQ sink is explicitly set to 100% and unmuted when created; user volume and mute stay on the final speaker. This is an estimated frequency-response margin, not a peak limiter or loudness normalizer, and boosting speaker volume above 100% can still distort. Changing a preset during playback briefly interrupts audio.

Preferences are stored at `~/.config/vinyl-streamer/equalizer.json` (`XDG_CONFIG_HOME` is respected), separately from temporary stream state. `VINYL_EQ_SETTINGS_PATH` overrides this path. Choosing a preset while stopped saves it without starting audio.

The app creates its own transient `vinyl-streamer-eq-*.service` user service and runtime configuration. These survive an API restart, allowing the app to recover control of an active stream. **Stop streaming** also stops the associated equalizer. Cleanup failures are reported and retried on subsequent status checks. The app does not restart PipeWire or change its global configuration.

For diagnostics:

```bash
pipewire --version
systemctl --user list-units 'vinyl-streamer-eq-*' --all --no-pager
journalctl --user -u 'vinyl-streamer-eq-*' -n 60 --no-pager
```

After updating, test all presets on the actual Pi and speaker, including Stop/Start, volume, mute and restarting the API during playback. Automated tests cover custom-band validation, persistence, route recovery and the headroom calculation. An earlier isolated Linux PipeWire audio test checked the preset filters and stereo separation. The updated custom curves and volume behavior still need an audible hardware check. Stop streaming before updating so the next stream uses the new filter configuration.

## iPhone and Android home screen

Use the same Pi address consistently: browser preferences and home-screen apps belong to the exact address (origin) you opened. The Pi and phone must be on the same reachable network.

- **iPhone:** open the app in Safari, choose Share, then Add to Home Screen. Leave the name as **Vinyl Streamer**. If Safari shows an Open as Web App option, enable it. Launch from the new icon.
- **Android:** open the app in Chrome, then choose Add to Home screen or Install app from the menu. The app supplies 192px/512px icons plus a maskable icon for Android's different icon shapes.
- **Existing shortcut:** after updating, remove the old home-screen icon and add it again if its name or icon does not refresh. Deleting a shortcut does not delete the Pi installation.

The current local HTTP address continues to work for control. Chrome's full install promotion/standalone PWA experience requires HTTPS; over a private HTTP address Android may offer only a browser shortcut. Metadata alone cannot remove this browser restriction. Full installation needs HTTPS trusted by the phone; it does not require making the Pi publicly accessible. See [Chrome installation criteria](https://web.dev/articles/install-criteria) and [WebKit home-screen support](https://webkit.org/blog/17333/webkit-features-in-safari-26-0/).

The page supports safe areas around notches and home indicators, native dark form controls and large touch targets. It refreshes live status when brought back to the foreground or the network returns. No offline audio control or API-response caching is implemented: the Pi must be reachable for its controls to work.

The source icon is `app/static/icons/icon.svg`. PNG/ICO exports are committed, so installation on the Pi requires no graphics tools. Developers can rebuild them using `python scripts/build_icons.py` (or add `--browser /path/to/chrome`) after installing the development requirements. The SVG keeps the record within Android's maskable safe zone.

The browser check supports `--engine webkit` after `python -m playwright install webkit`. Chromium/WebKit emulation checks layouts and assets; final Add to Home Screen and status-bar appearance must be checked on actual phones.

## Troubleshooting

```bash
journalctl --user -u vinyl-streamer-app -n 60 --no-pager
./venv/bin/python scripts/smoke_check.py
pactl list short modules
pactl list short sources
pactl list short sinks
```

- **Speaker found, no usable output:** network discovery is separate from RAOP output creation. Check that `module-raop-discover` loads and that the speaker is compatible. PipeWire usually names outputs `raop_sink.*`; PulseAudio may use `raop_output.*`.
- **No audio input:** check the USB cable and exclude `.monitor` entries when inspecting capture inputs.
- **Old audio keeps playing after stopping the service:** the loopback is owned by the audio server and survives an API restart. The new app can recover control of it. Use its Stop streaming button.
- **Port already in use:** compare `MainPID` from `systemctl --user show` with `sudo ss -ltnp 'sport = :8000'` and check for an older service.
- **No space left:** inspect `df -h /`, `df -i /` and `sudo journalctl --disk-usage`. Review old logs and caches before deleting anything. Installing with `--no-cache-dir` avoids retaining pip downloads.
- **Buffer setting:** 40?500 ms controls the local loopback buffer, not the total AirPlay/network delay.
- **Status versus sound:** Stream active means the audio loopback exists. It cannot confirm the speaker is producing sound.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `VINYL_HOST` | `0.0.0.0` | Listening address |
| `VINYL_PORT` | `8000` | Listening port |
| `VINYL_STATE_PATH` | `<temporary-directory>/vinyl_streamer_state.json` | Atomically written stream state; normally `/tmp/vinyl_streamer_state.json` on the Pi |

The state filename remains unchanged so the new app can recover an existing stream. Stale module IDs are checked against the audio server before use. An audio-server restart clears stale running state; a state-write failure leaves the active module controllable in memory and reports a warning.

For service overrides, use `systemctl --user edit vinyl-streamer-app`, add an `[Service]` section with the required `Environment=...` values, then reload and restart the service. Read the status/logs after a change.
