from __future__ import annotations

import logging
from dataclasses import asdict, replace
from threading import RLock

from app import audio
from app.state import load_state, save_state

logger = logging.getLogger(__name__)


class StreamConflict(RuntimeError):
    pass


class StreamController:
    """Serialize changes and verify saved module IDs before controlling them.

    Run one API worker: this lock protects one audio session in one process.
    """

    def __init__(self) -> None:
        self.lock = RLock()
        self.state = load_state()
        self.persistence_warning: str | None = None
        self.stream_warning: str | None = None

    def _persist(self) -> None:
        try:
            save_state(self.state)
            self.persistence_warning = None
        except OSError:
            logger.exception("Could not save stream state")
            self.persistence_warning = "De streamstatus kon niet worden opgeslagen. Controleer de schijfruimte en schrijfrechten."

    def _reconcile(self) -> bool:
        modules = audio.list_modules()
        module = next((item for item in modules if item.id == self.state.loopback_module), None)
        owned = module is not None and audio.is_stream_module(module, self.state.source, self.state.sink)
        running = self.state.running
        if owned:
            self.state.running = True
        else:
            self.state.running = False
            self.state.loopback_module = None
            if running:
                self.stream_warning = "De audiostream is onderbroken. Start streaming opnieuw."
        if running != self.state.running:
            self._persist()
        return bool(owned)

    def status(self) -> dict:
        with self.lock:
            self._reconcile()
            volume = None
            muted = None
            warnings = []
            if self.stream_warning:
                warnings.append(self.stream_warning)
            if self.state.running and self.state.sink:
                sinks = audio.list_sinks()
                sources = audio.list_sources()
                if not any(item.name == self.state.sink for item in sinks):
                    warnings.append("De actieve speaker is niet beschikbaar. Stop de stream en controleer de speaker.")
                elif not any(item.name == self.state.source for item in sources):
                    warnings.append("De audio-input is niet beschikbaar. Controleer de USB-aansluiting.")
                else:
                    try:
                        volume = audio.get_sink_volume(self.state.sink)
                        muted = audio.get_sink_mute(self.state.sink)
                    except RuntimeError as exc:
                        warnings.append(str(exc))
            if self.persistence_warning:
                warnings.append(self.persistence_warning)
            return {**asdict(self.state), "volume": volume, "muted": muted, "warnings": warnings}

    def connect(self, source: str | None, sink: str, latency_ms: int) -> dict:
        with self.lock:
            if self._reconcile():
                raise StreamConflict("Er is al een stream actief. Stop die eerst.")
            raop_module = audio.ensure_raop_module()
            sources = audio.list_sources()
            candidates = [item for item in sources if not item.name.endswith(".monitor") and not item.name.startswith("auto_null")]
            source = source or audio.pick_default_source(candidates)
            if not source or not any(item.name == source for item in candidates):
                raise ValueError("Geen geldige audio-input beschikbaar. Controleer de USB-aansluiting.")
            if not any(item.name == sink and audio.is_airplay_sink(item) for item in audio.list_sinks()):
                raise ValueError("Deze speaker is niet beschikbaar als AirPlay-audio-uitgang. Vernieuw de apparaten.")
            loopback = audio.start_loopback(source, sink, latency_ms)
            self.state = replace(self.state, source=source, sink=sink, latency_ms=latency_ms,
                                 loopback_module=loopback, raop_module=raop_module, running=True)
            self.stream_warning = None
            self._persist()
            logger.info("Stream started: %s -> %s (module %s)", source, sink, loopback)
            return {**asdict(self.state), "warnings": [self.persistence_warning] if self.persistence_warning else []}

    def disconnect(self) -> dict:
        with self.lock:
            if self._reconcile():
                audio.stop_loopback(self.state.loopback_module)
            self.state.running = False
            self.state.loopback_module = None
            self.stream_warning = None
            self._persist()
            logger.info("Stream stopped")
            return {**asdict(self.state), "warnings": [self.persistence_warning] if self.persistence_warning else []}

    def set_volume(self, volume: int | None = None, muted: bool | None = None, sink: str | None = None) -> None:
        with self.lock:
            if not self._reconcile():
                raise StreamConflict("Start eerst streaming om het volume te regelen.")
            if sink is not None and sink != self.state.sink:
                raise StreamConflict("De actieve speaker is gewijzigd. Probeer opnieuw.")
            if volume is not None:
                audio.set_sink_volume(self.state.sink, volume)
            if muted is not None:
                audio.set_sink_mute(self.state.sink, muted)
