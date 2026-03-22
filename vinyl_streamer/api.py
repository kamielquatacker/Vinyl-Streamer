from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from vinyl_streamer import audio, discovery
from vinyl_streamer.state import StreamState, load_state, save_state


app = FastAPI(title="Vinyl Streamer")
state = load_state()


class ConnectRequest(BaseModel):
    source: str | None = None
    sink: str
    latency_ms: int = 80


class VolumeRequest(BaseModel):
    sink: str
    volume: int


@app.get("/api/status")
def get_status() -> StreamState:
  volume = None
  if state.sink:
    try:
      volume = audio.get_sink_volume(state.sink)
    except RuntimeError:
      volume = None
  return {
    **state.__dict__,
    "volume": volume,
  }


@app.get("/api/devices")
def get_devices() -> dict:
  sinks = [sink for sink in audio.list_sinks() if sink.name.startswith("raop_sink.")]
  sinks.sort(key=lambda item: item.name)
  sources = [
    source
    for source in audio.list_sources()
    if not source.name.endswith(".monitor") and not source.name.startswith("auto_null")
  ]
  sources.sort(key=lambda item: item.name)
  return {
    "sources": sources,
    "sinks": sinks,
    "airplay": discovery.discover(),
  }


@app.post("/api/connect")
def connect(req: ConnectRequest) -> StreamState:
    if state.running:
        raise HTTPException(status_code=400, detail="Stream already running")

    raop_module = audio.ensure_raop_module()
    source = req.source or audio.pick_default_source()
    if not source:
        raise HTTPException(status_code=404, detail="No audio source found")

    try:
        loopback_id = audio.start_loopback(source, req.sink, req.latency_ms)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    state.source = source
    state.sink = req.sink
    state.loopback_module = loopback_id
    state.raop_module = raop_module
    state.latency_ms = req.latency_ms
    state.running = True
    save_state(state)
    return state


@app.post("/api/disconnect")
def disconnect() -> StreamState:
    if state.loopback_module:
        try:
            audio.stop_loopback(state.loopback_module)
        except RuntimeError:
            pass
    state.running = False
    state.loopback_module = None
    save_state(state)
    return state


@app.post("/api/volume")
def set_volume(req: VolumeRequest) -> dict:
    try:
        audio.set_sink_volume(req.sink, req.volume)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Vinyl Streamer</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; max-width: 760px; color: #1f2937; }
    h1 { margin-bottom: 0.25rem; }
    select, button, input { padding: 0.55rem; margin: 0.25rem 0; }
  .row { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; }
  .row.no-wrap { flex-wrap: nowrap; }
  .grow { flex: 1; min-width: 0; }
  .btn-small { padding: 0.35rem 0.6rem; }
    .status { padding: 0.75rem 1rem; border-radius: 10px; background: #f3f4f6; display: grid; gap: 0.35rem; }
    .badge { display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.2rem 0.6rem; border-radius: 999px; font-size: 0.85rem; }
    .badge.ok { background: #dcfce7; color: #166534; }
    .badge.off { background: #fee2e2; color: #991b1b; }
    .muted { color: #6b7280; font-size: 0.9rem; }
    .section { margin-top: 1.2rem; }
    .label { font-weight: 600; }
    .error { color: #b91c1c; font-weight: 600; }
  </style>
</head>
<body>
  <h1>Vinyl Streamer</h1>
  <p class="muted">Realtime streaming van je vinyl input naar AirPlay.</p>
  <div class="status" id="status">
    <div>
      <span class="badge off" id="statusBadge">Niet verbonden</span>
    </div>
    <div><span class="label">Sink:</span> <span id="statusSink">-</span></div>
    <div><span class="label">Source:</span> <span id="statusSource">-</span></div>
    <div><span class="label">Latency:</span> <span id="statusLatency">-</span></div>
    <div class="muted" id="statusUpdated">Laatste update: -</div>
    <div class="error" id="statusError"></div>
  </div>

  <div class="section">
    <label>AirPlay sink</label><br />
    <div class="row">
      <select id="sink"></select>
      <button type="button" onclick="safeRefreshDevices()">Refresh</button>
    </div>
  </div>

  <div class="section">
    <label>Audio input (source)</label><br />
    <div class="row">
      <select id="source"></select>
      <button type="button" onclick="safeRefreshDevices()">Refresh</button>
    </div>
  </div>

  <div class="section">
    <label>Latency (ms)</label><br />
    <input id="latency" type="number" min="40" max="500" value="80" />
  </div>

  <div class="row section">
    <button id="connectBtn" onclick="connectStream()">Connect</button>
    <button id="disconnectBtn" onclick="disconnectStream()">Disconnect</button>
  </div>

  <div class="section">
    <label>Volume (%)</label><br />
    <div class="row no-wrap">
      <button type="button" class="btn-small" onclick="stepVolume(-5)">-</button>
      <input id="volume" class="grow" type="range" min="0" max="150" step="5" value="20" oninput="setVolumeLabel(this.value); setVolume(this.value)" />
      <button type="button" class="btn-small" onclick="stepVolume(5)">+</button>
      <span id="volumeValue" class="muted">20%</span>
    </div>
  </div>

<script>
const STATUS_INTERVAL_MS = 3000;

function prettyName(name) {
  if (!name) return '-';
  return name
    .replace(/^alsa_input\./, '')
    .replace(/^alsa_output\./, '')
    .replace(/^raop_sink\./, '')
    .replace(/\.local\./, ' ')
    .replace(/\./g, ' ');
}

function labelSink(sink, airplay) {
  const candidate = airplay.find(dev => sink.name.includes(dev.friendly_name) || sink.name.includes(dev.address));
  if (candidate) {
    return candidate.display_name;
  }
  return prettyName(sink.name);
}

async function refreshStatus() {
  const statusError = document.getElementById('statusError');
  statusError.textContent = '';
  const status = await fetch('/api/status').then(r => r.json());
  document.getElementById('statusSink').textContent = status.sink ? prettyName(status.sink) : '-';
  document.getElementById('statusSource').textContent = status.source ? prettyName(status.source) : '-';
  document.getElementById('statusLatency').textContent = status.latency_ms ? `${status.latency_ms} ms` : '-';
  document.getElementById('statusUpdated').textContent = `Laatste update: ${new Date().toLocaleTimeString()}`;
  const badge = document.getElementById('statusBadge');
  if (status.running) {
    badge.textContent = 'Verbonden';
    badge.className = 'badge ok';
  } else {
    badge.textContent = 'Niet verbonden';
    badge.className = 'badge off';
  }
  if (status.volume !== null && status.volume !== undefined) {
    const slider = document.getElementById('volume');
    slider.value = status.volume;
    setVolumeLabel(status.volume);
  }
}

async function refreshDevices() {
  const data = await fetch('/api/devices').then(r => r.json());
  const sinkSelect = document.getElementById('sink');
  const sourceSelect = document.getElementById('source');
  const currentSink = sinkSelect.value;
  const currentSource = sourceSelect.value;

  sinkSelect.innerHTML = '';
  data.sinks.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.name;
    opt.textContent = labelSink(s, data.airplay);
    sinkSelect.appendChild(opt);
  });

  sourceSelect.innerHTML = '';
  data.sources.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.name;
    opt.textContent = prettyName(s.name);
    sourceSelect.appendChild(opt);
  });

  if (currentSink) sinkSelect.value = currentSink;
  if (currentSource) sourceSelect.value = currentSource;
}

async function safeRefreshStatus() {
  try {
    await refreshStatus();
  } catch (err) {
    document.getElementById('statusError').textContent = 'Fout bij ophalen van status.';
  }
}

async function safeRefreshDevices() {
  try {
    await refreshDevices();
  } catch (err) {
    document.getElementById('statusError').textContent = 'Fout bij ophalen van devices.';
  }
}

async function connectStream() {
  setLoading(true, 'Verbinden...');
  const sink = document.getElementById('sink').value;
  const source = document.getElementById('source').value;
  const latency = Number(document.getElementById('latency').value);
  try {
    await fetch('/api/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sink, source, latency_ms: latency })
    });
  } finally {
    setLoading(false, '');
  }
  safeRefreshStatus();
}

async function disconnectStream() {
  setLoading(true, 'Disconnecten...');
  try {
    await fetch('/api/disconnect', { method: 'POST' });
  } finally {
    setLoading(false, '');
  }
  safeRefreshStatus();
}

function setVolumeLabel(value) {
  document.getElementById('volumeValue').textContent = `${value}%`;
}

async function setVolume(value) {
  const sink = document.getElementById('sink').value;
  await fetch('/api/volume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sink, volume: Number(value) })
  });
}

function stepVolume(delta) {
  const slider = document.getElementById('volume');
  const current = Number(slider.value);
  const next = Math.max(0, Math.min(150, current + delta));
  slider.value = next;
  setVolumeLabel(next);
  setVolume(next);
}

function setLoading(isLoading, message) {
  const badge = document.getElementById('statusBadge');
  const connectBtn = document.getElementById('connectBtn');
  const disconnectBtn = document.getElementById('disconnectBtn');
  connectBtn.disabled = isLoading;
  disconnectBtn.disabled = isLoading;
  if (isLoading) {
    badge.textContent = message;
    badge.className = 'badge off';
  }
}

const volumeSlider = document.getElementById('volume');
volumeSlider.value = 20;
setVolumeLabel(volumeSlider.value);

safeRefreshDevices();
safeRefreshStatus();
setInterval(safeRefreshStatus, STATUS_INTERVAL_MS);
</script>
</body>
</html>
"""
