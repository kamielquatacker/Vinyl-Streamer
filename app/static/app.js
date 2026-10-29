const $ = id => document.getElementById(id);
const model = {
  devices: { sinks: [], sources: [], airplay: [] }, speakers: [], selected: '',
  status: { running: false }, online: false, loaded: false, busy: false,
  refreshing: false, polling: false, volumePending: null, volumeWorking: false,
  volumeTimer: null, editingVolume: false, discoveryTimer: null,
  revision: 0, muteWorking: false, eqWorking: false, eqDraft: null, eqBandsDraft: null,
};

function message(id, text = '') {
  $(id).textContent = text;
  $(id).hidden = !text;
}

export async function api(path, body) {
  const abort = new AbortController();
  const timeout = setTimeout(() => abort.abort(), 30000);
  try {
    const response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: abort.signal, cache: 'no-store',
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = data?.detail;
      throw new Error(typeof detail === 'string' ? detail : response.status === 422
        ? 'Controleer de gekozen speaker, audio-input en buffer (40–500 ms).'
        : 'De aanvraag is mislukt. Probeer opnieuw.');
    }
    if (data === null) throw new Error('De server gaf geen geldig antwoord.');
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('De Pi reageert niet op tijd. Controleer de status voordat je opnieuw probeert.');
    if (error instanceof TypeError) throw new Error('De Pi is niet bereikbaar. Controleer je netwerkverbinding.');
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function prettyName(name) {
  return (name || '').replace(/^(alsa_input|alsa_output|raop_sink|raop_output|raop)\./, '').replace(/[_.]/g, ' ').trim();
}

const normalized = value => (value || '').toLowerCase().replace(/[^a-z0-9]/g, '');

export function buildSpeakers(devices) {
  const used = new Set();
  const speakers = devices.sinks.map(sink => {
    const key = normalized(sink.name);
    const found = devices.airplay.filter(device =>
      [device.address, device.friendly_name].some(value => normalized(value).length > 2 && key.includes(normalized(value))));
    found.forEach(device => used.add(device));
    const device = found[0];
    return { id: sink.name, name: device?.friendly_name || prettyName(sink.name), ready: true, device };
  });
  const seen = new Set();
  devices.airplay.forEach(device => {
    const identity = `${device.address}|${device.friendly_name}`;
    if (used.has(device) || seen.has(identity)) return;
    seen.add(identity);
    speakers.push({ id: identity, name: device.friendly_name, ready: false, device });
  });
  return speakers;
}

function speakerName(sink) {
  return model.speakers.find(speaker => speaker.id === sink)?.name || prettyName(sink) || 'Speaker';
}

function sourceName(name) {
  return name?.toLowerCase().includes('usb') ? 'USB-audio' : prettyName(name) || 'Audio-input';
}

function renderSpeakers() {
  const container = $('speakers');
  const focusId = container.contains(document.activeElement) ? document.activeElement.dataset.sink : null;
  container.replaceChildren();
  const speakers = [...model.speakers];
  if (model.status.running && !speakers.some(speaker => speaker.id === model.status.sink)) {
    speakers.unshift({ id: model.status.sink, name: speakerName(model.status.sink), ready: false });
  }
  speakers.forEach(speaker => {
    const active = model.status.running && model.status.sink === speaker.id;
    const selected = active || !model.status.running && model.selected === speaker.id;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `speaker${selected ? ' selected' : ''}${speaker.ready ? '' : ' unavailable'}`;
    button.disabled = model.busy || model.eqWorking || model.status.running || !speaker.ready;
    button.dataset.sink = speaker.id;
    button.setAttribute('aria-pressed', String(selected));
    const icon = document.createElement('span');
    icon.className = 'speaker-symbol';
    icon.setAttribute('aria-hidden', 'true');
    const copy = document.createElement('span');
    copy.className = 'speaker-copy';
    const name = document.createElement('span');
    name.className = 'speaker-name';
    name.textContent = speaker.name;
    const state = document.createElement('span');
    state.className = 'speaker-state';
    state.textContent = active ? speaker.ready ? 'Actieve audio-uitgang' : 'Actieve uitgang niet beschikbaar'
      : speaker.ready ? 'Klaar om te streamen' : 'Gevonden · audio-uitgang niet beschikbaar';
    copy.append(name, state);
    const dot = document.createElement('span');
    dot.className = 'selection-dot';
    dot.setAttribute('aria-hidden', 'true');
    button.append(icon, copy, dot);
    button.addEventListener('click', () => { model.selected = speaker.id; render(); });
    container.append(button);
  });
  if (!speakers.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = model.loaded ? 'Nog geen speakers gevonden' : 'Speakers zoeken…';
    container.append(empty);
  }
  if (focusId) [...container.children].find(child => child.dataset.sink === focusId)?.focus();
  container.setAttribute('aria-busy', String(model.refreshing));
}

function renderDetails() {
  const selected = model.speakers.find(speaker => speaker.id === (model.status.running ? model.status.sink : model.selected));
  const rows = {
    'Audio-uitgang': model.status.running ? model.status.sink : model.selected || '—',
    'Netwerkadres': selected?.device?.address || '—',
    'Audio-input': model.status.running ? model.status.source : $('source').value || 'Automatisch',
    'Loopbackmodule': model.status.loopback_module || '—',
  };
  $('technicalDetails').replaceChildren();
  Object.entries(rows).forEach(([label, value]) => {
    const term = document.createElement('dt');
    const description = document.createElement('dd');
    term.textContent = label;
    description.textContent = value;
    $('technicalDetails').append(term, description);
  });
}

function render() {
  const { status, busy, online, devices } = model;
  const ready = model.speakers.some(speaker => speaker.ready && speaker.id === model.selected);
  $('status').textContent = busy ? 'Even geduld…' : !online ? 'Status niet beschikbaar'
    : status.running ? 'Stream actief' : 'Stand-by';
  $('liveDot').classList.toggle('active', online && status.running && !status.warnings?.length);
  $('playbackTitle').textContent = busy ? status.running ? 'Streaming stoppen…' : 'Streaming starten…'
    : !online ? 'Verbinding controleren' : status.running ? speakerName(status.sink) : 'Klaar voor je plaat';
  $('route').textContent = status.running ? `${sourceName(status.source)} → ${speakerName(status.sink)}`
    : 'Kies een speaker en zet je plaat op.';
  $('streamButton').textContent = busy ? 'Even geduld…' : status.running ? 'Stop streaming' : 'Start streaming';
  $('streamButton').classList.toggle('stop', status.running);
  $('streamButton').disabled = busy || model.eqWorking || !online || !status.running && (!ready || !devices.sources.length);
  $('startHint').textContent = status.running ? 'De Pi stuurt audio naar deze uitgang.'
    : !model.loaded ? 'Apparaten worden opgehaald.' : !devices.sources.length ? 'Sluit eerst een audio-input aan.'
    : !ready ? 'Kies een beschikbare speaker om te starten.' : '';
  $('source').disabled = busy || model.eqWorking || status.running || !devices.sources.length;
  $('latency').disabled = busy || model.eqWorking || status.running;
  $('refreshButton').disabled = model.refreshing;
  $('refreshButton').textContent = model.refreshing ? 'Zoeken…' : 'Vernieuwen';
  $('volumeControls').disabled = busy || model.eqWorking || !online || !status.running || status.volume == null;
  $('volumeTarget').textContent = status.running ? `Actieve speaker: ${speakerName(status.sink)}` : 'Beschikbaar tijdens streaming.';
  if (!model.volumePending && !model.volumeWorking && !model.editingVolume) {
    const volume = status.running ? status.volume : null;
    $('volumeValue').textContent = volume == null ? '—' : `${volume}%`;
    if (volume != null) {
      // Preserve an existing boosted volume without reducing it just by opening the UI.
      if (volume > 100) $('boost').checked = true;
      $('volume').max = $('boost').checked ? '150' : '100';
      $('volume').value = volume;
    }
  }
  const muteLabel = status.muted ? 'Geluid aan' : 'Dempen';
  $('muteButton').setAttribute('aria-label', muteLabel);
  $('muteButton').title = muteLabel;
  $('muteButton').setAttribute('aria-pressed', String(Boolean(status.muted)));
  renderSpeakers();
  renderDetails();
  renderEqualizer();
}

function renderEqualizer() {
  const settings = model.eqDraft || (model.eqBandsDraft
    ? { ...model.status.equalizer, preset: 'custom', bands: model.eqBandsDraft } : model.status.equalizer);
  const available = model.status.equalizer?.available;
  const presets = model.status.equalizer?.presets || [];
  const select = $('eqPreset');
  if (JSON.stringify(presets) !== select.dataset.presets) {
    select.replaceChildren();
    presets.forEach(preset => {
      const option = document.createElement('option');
      option.value = preset.id;
      option.textContent = preset.name;
      select.append(option);
    });
    select.dataset.presets = JSON.stringify(presets);
  }
  $('eqEnabled').checked = Boolean(settings?.enabled);
  if (settings?.preset) select.value = settings.preset;
  const disabled = model.busy || model.eqWorking || model.volumeWorking || model.muteWorking || !model.online || !available;
  $('eqEnabled').disabled = model.busy || model.eqWorking || model.volumeWorking || model.muteWorking || !model.online || (!available && !settings?.enabled);
  select.disabled = disabled;
  const bands = settings?.bands || [0, 0, 0, 0, 0];
  bands.forEach((gain, index) => {
    const slider = $(`eqBand${index}`);
    slider.disabled = disabled;
    slider.value = gain;
    const label = `${gain > 0 ? '+' : ''}${gain} dB`;
    slider.setAttribute('aria-valuetext', label);
    $(`eqBandValue${index}`).textContent = label;
  });
  const preset = presets.find(item => item.id === settings?.preset);
  $('eqHint').textContent = model.eqWorking ? 'Geluid aanpassen...'
    : !model.status.equalizer ? 'Instellingen ophalen...'
    : !available ? 'Equaliser vereist PipeWire en een gebruikerssessie op de Pi.'
    : !settings?.enabled ? 'Uit. Je audio gaat rechtstreeks naar de speaker.'
    : !model.status.running ? `${preset?.description || ''} Wordt toegepast bij starten.`
    : !model.status.equalizer.active ? 'Equaliser niet beschikbaar. Schakel uit of start streaming opnieuw.'
    : `${preset?.description || ''} ${model.status.equalizer.preamp_db < 0 ? 'Bij versterkte banden kan het geluid iets zachter zijn. ' : ''}Bij wisselen kan de audio kort onderbreken.`;
}

async function configureEqualizer() {
  if (model.eqWorking || model.busy) return;
  const preset = $('eqPreset').value;
  model.eqDraft = { enabled: $('eqEnabled').checked, preset,
    bands: model.eqBandsDraft || model.status.equalizer?.custom_bands || [0, 0, 0, 0, 0] };
  model.eqWorking = true;
  model.revision++;
  render();
  try {
    model.status = await api('/api/equalizer', model.eqDraft);
    message('eqError');
    message('streamWarning', (model.status.warnings || []).join(' '));
  } catch (error) {
    message('eqError', error.message);
  } finally {
    model.revision++;
    model.eqDraft = null;
    model.eqBandsDraft = null;
    model.eqWorking = false;
    render();
    await refreshStatus();
  }
}

async function refreshStatus() {
  if (model.polling || model.eqBandsDraft || model.busy || model.eqWorking || model.volumeWorking || model.volumePending || model.muteWorking) return;
  model.polling = true;
  const revision = model.revision;
  try {
    const status = await api('/api/status');
    if (model.busy || revision !== model.revision) return;
    model.status = status;
    model.online = true;
    if (status.running) {
      model.selected = status.sink;
      $('latency').value = status.latency_ms;
    }
    message('statusError');
    message('streamWarning', (status.warnings || []).join(' '));
    $('updated').textContent = `Bijgewerkt om ${new Date().toLocaleTimeString('nl-BE', {hour: '2-digit', minute: '2-digit'})}`;
  } catch (error) {
    if (revision !== model.revision) return;
    model.online = false;
    message('statusError', error.message);
  } finally {
    model.polling = false;
    render();
  }
}

async function refreshDevices() {
  if (model.refreshing) return;
  clearTimeout(model.discoveryTimer);
  model.refreshing = true;
  render();
  try {
    const devices = await api('/api/devices');
    model.devices = devices;
    model.speakers = buildSpeakers(devices);
    model.loaded = true;
    if (!model.speakers.some(speaker => speaker.ready && speaker.id === model.selected)) {
      model.selected = model.speakers.find(speaker => speaker.ready)?.id || '';
    }
    const oldSource = $('source').value;
    $('source').replaceChildren();
    const automatic = document.createElement('option');
    automatic.value = '';
    automatic.textContent = devices.sources.length ? 'Automatisch (voorkeur voor USB)' : 'Geen audio-input beschikbaar';
    $('source').append(automatic);
    devices.sources.forEach(source => {
      const option = document.createElement('option');
      option.value = source.name;
      option.textContent = prettyName(source.name);
      $('source').append(option);
    });
    const preferred = model.status.running ? model.status.source : oldSource;
    if (devices.sources.some(source => source.name === preferred)) $('source').value = preferred;
    const unavailable = model.speakers.some(speaker => !speaker.ready);
    $('deviceHint').textContent = devices.discovering ? 'Speakers zoeken…'
      : !model.speakers.length ? 'Zet je speaker aan en verbind hem met hetzelfde netwerk als de Pi.'
      : unavailable ? 'Speaker gevonden zonder audio-uitgang? Vernieuw over enkele seconden. Controleer bij aanhoudende problemen de RAOP-module op de Pi.' : '';
    message('deviceError');
    message('deviceWarning', (devices.warnings || []).join(' '));
  } catch (error) {
    message('deviceError', error.message);
  } finally {
    model.refreshing = false;
    render();
    model.discoveryTimer = setTimeout(refreshDevices, model.devices.discovering ? 2000 : 12000);
  }
}

async function toggleStream() {
  if (model.busy || $('streamButton').disabled) return;
  if (!model.status.running && !$('latency').validity.valid) {
    $('latency').closest('details.advanced').open = true;
    $('latency').reportValidity();
    return;
  }
  model.busy = true;
  model.revision++;
  clearTimeout(model.volumeTimer);
  model.volumePending = null;
  render();
  try {
    model.status = model.status.running ? await api('/api/disconnect', {}) : await api('/api/connect', {
      sink: model.selected, source: $('source').value || null, latency_ms: Number($('latency').value),
    });
    message('actionError');
    message('actionWarning', (model.status.warnings || []).join(' '));
    message('volumeError');
    message('streamWarning');
  } catch (error) {
    message('actionError', error.message);
  } finally {
    model.revision++;
    model.busy = false;
    render();
    await refreshStatus();
  }
}

function queueVolume(value) {
  if ($('volumeControls').disabled) return;
  model.revision++;
  value = Math.max(0, Math.min(Number($('volume').max), Number(value)));
  $('volume').value = value;
  $('volumeValue').textContent = `${value}%`;
  model.volumePending = { volume: value, sink: model.status.sink };
  clearTimeout(model.volumeTimer);
  model.volumeTimer = setTimeout(flushVolume, 180);
}

async function flushVolume() {
  if (model.volumeWorking || !model.volumePending) return;
  model.volumeWorking = true;
  try {
    while (model.volumePending) {
      const pending = model.volumePending;
      model.volumePending = null;
      try {
        await api('/api/volume', pending);
        if (model.status.sink === pending.sink) model.status.volume = pending.volume;
        message('volumeError');
      } catch (error) {
        model.volumePending = null;
        message('volumeError', error.message);
      }
    }
  } finally {
    model.revision++;
    model.volumeWorking = false;
    render();
  }
}

async function toggleMute() {
  model.revision++;
  model.muteWorking = true;
  $('muteButton').disabled = true;
  const sink = model.status.sink;
  const muted = !model.status.muted;
  try {
    await api('/api/mute', { sink, muted });
    if (model.status.sink === sink) model.status.muted = muted;
    message('volumeError');
  } catch (error) {
    message('volumeError', error.message);
  } finally {
    model.revision++;
    model.muteWorking = false;
    $('muteButton').disabled = false;
    render();
  }
}

for (let index = 0; index < 5; index++) {
  $(`eqBand${index}`).addEventListener('input', () => {
    model.revision++;
    model.eqBandsDraft = Array.from({ length: 5 }, (_, band) => Number($(`eqBand${band}`).value));
    renderEqualizer();
  });
  $(`eqBand${index}`).addEventListener('change', configureEqualizer);
}
$('eqEnabled').addEventListener('change', configureEqualizer);
$('eqPreset').addEventListener('change', configureEqualizer);
$('streamButton').addEventListener('click', toggleStream);
$('refreshButton').addEventListener('click', refreshDevices);
$('volume').addEventListener('input', event => queueVolume(event.target.value));
$('volume').addEventListener('pointerdown', () => { model.editingVolume = true; });
window.addEventListener('pointerup', () => { model.editingVolume = false; });
$('volume').addEventListener('change', () => { model.editingVolume = false; flushVolume(); });
$('volumeDown').addEventListener('click', () => queueVolume(Number($('volume').value) - 5));
$('volumeUp').addEventListener('click', () => queueVolume(Number($('volume').value) + 5));
$('muteButton').addEventListener('click', toggleMute);
$('boost').addEventListener('change', () => {
  $('volume').max = $('boost').checked ? '150' : '100';
  if (!$('boost').checked && model.status.volume > 100) queueVolume(100);
});
$('source').addEventListener('change', renderDetails);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { refreshStatus(); refreshDevices(); }
});
window.addEventListener('pageshow', event => {
  if (event.persisted) { refreshStatus(); refreshDevices(); }
});
window.addEventListener('online', () => { refreshStatus(); refreshDevices(); });
render();
refreshStatus();
refreshDevices();
setInterval(() => { if (!document.hidden) refreshStatus(); }, 3000);
