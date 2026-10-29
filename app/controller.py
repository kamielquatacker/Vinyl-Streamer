from __future__ import annotations

import logging
from dataclasses import asdict, replace
from threading import RLock

from app import audio, equalizer
from app.state import load_state, save_state

logger = logging.getLogger(__name__)


class StreamConflict(RuntimeError):
    pass


class StreamController:
    """One worker controls the audio session, including owned EQ resources."""

    def __init__(self) -> None:
        self.lock = RLock()
        self.state = load_state()
        self.engine = equalizer.EqualizerEngine()
        self.eq_settings = equalizer.load_settings()
        if self.state.running and self.state.eq_unit:
            self.eq_settings = equalizer.Settings(True, self.state.eq_preset)
        self.persistence_warning: str | None = None
        self.preferences_warning: str | None = None
        self.stream_warning: str | None = None
        self.cleanup_warning: str | None = None

    def _persist(self) -> None:
        try:
            save_state(self.state)
            self.persistence_warning = None
        except OSError:
            logger.exception("Could not save stream state")
            self.persistence_warning = "De streamstatus kon niet worden opgeslagen. Controleer schijfruimte en schrijfrechten."

    def _save_preferences(self) -> None:
        try:
            equalizer.save_settings(self.eq_settings)
            self.preferences_warning = None
        except OSError:
            logger.exception("Could not save equalizer preferences")
            self.preferences_warning = "De equaliserinstelling is toegepast, maar kon niet worden opgeslagen voor een volgende herstart."

    def _queue_cleanup(self, unit: str | None) -> None:
        if unit and unit not in self.state.eq_cleanup:
            self.state.eq_cleanup.append(unit)

    def _clear_filter(self) -> None:
        self.state.eq_unit = self.state.eq_sink = self.state.eq_preset = None

    def _cleanup(self) -> None:
        remaining = []
        for unit in self.state.eq_cleanup:
            if unit == self.state.eq_unit:
                continue
            try:
                self.engine.stop(unit)
            except (RuntimeError, OSError):
                logger.warning("Equalizer cleanup will be retried: %s", unit, exc_info=True)
                remaining.append(unit)
        if remaining != self.state.eq_cleanup:
            self.state.eq_cleanup = remaining
            self._persist()
        self.cleanup_warning = "Een oude equaliser kon nog niet worden opgeruimd. De app probeert dit opnieuw." if remaining else None

    def _reconcile(self) -> bool:
        before = asdict(self.state)
        modules = audio.list_modules()
        module = next((item for item in modules if item.id == self.state.loopback_module), None)
        route = self.state.eq_sink or self.state.sink
        owned = module is not None and audio.is_stream_module(module, self.state.source, route)
        if owned:
            self.state.running = True
        else:
            if self.state.running:
                self.stream_warning = "De audiostream is onderbroken. Start streaming opnieuw."
            self.state.running = False
            self.state.loopback_module = None
            self._queue_cleanup(self.state.eq_unit)
            self._clear_filter()
        if before != asdict(self.state):
            self._persist()
        self._cleanup()
        return bool(owned)

    def _snapshot(self, volume=None, muted=None, extra_warnings=(), filter_present=True) -> dict:
        warnings = [item for item in (self.stream_warning, self.persistence_warning,
                    self.preferences_warning, self.cleanup_warning, *extra_warnings) if item]
        return {
            **asdict(self.state), "volume": volume, "muted": muted, "warnings": warnings,
            "equalizer": {
                "enabled": self.eq_settings.enabled, "preset": self.eq_settings.preset,
                "active": bool(self.state.running and self.state.eq_unit and filter_present),
                "available": self.engine.available(),
                "preamp_db": equalizer.preamp_db(self.eq_settings.preset) if self.eq_settings.enabled else 0,
                "presets": [{"id": key, "name": value["name"], "description": value["description"]}
                            for key, value in equalizer.PRESETS.items()],
            },
        }

    def status(self) -> dict:
        with self.lock:
            self._reconcile()
            volume = muted = None
            warnings = []
            filter_present = True
            if self.state.running:
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
                if self.state.eq_sink:
                    filter_present = any(item.name == self.state.eq_sink for item in sinks)
                    if not filter_present:
                        warnings.append("De equaliser is niet beschikbaar. Stop de stream en start opnieuw, of schakel de equaliser uit.")
            return self._snapshot(volume, muted, warnings, filter_present)

    def _prepare_filter(self, settings: equalizer.Settings, target: str) -> tuple[str | None, str | None]:
        if not settings.enabled:
            return None, None
        if self.state.eq_cleanup:
            raise RuntimeError("Ruim eerst de oude equaliser op. Probeer de aanvraag opnieuw.")
        unit = equalizer.new_unit()
        # Record ownership before creating an external resource, for crash recovery.
        self._queue_cleanup(unit)
        self._persist()
        try:
            sink = self.engine.start(unit, target, settings.preset)
        except (RuntimeError, OSError) as exc:
            self._cleanup()
            raise RuntimeError(str(exc)) from exc
        return unit, sink

    def _activate_filter(self, unit: str | None, sink: str | None, preset: str) -> None:
        self.state.eq_unit, self.state.eq_sink = unit, sink
        self.state.eq_preset = preset if unit else None
        if unit in self.state.eq_cleanup:
            self.state.eq_cleanup.remove(unit)

    def connect(self, source: str | None, sink: str, latency_ms: int) -> dict:
        with self.lock:
            if self._reconcile():
                raise StreamConflict("Er is al een stream actief. Stop die eerst.")
            raop_module = audio.ensure_raop_module()
            candidates = [item for item in audio.list_sources() if not item.name.endswith(".monitor")
                          and not item.name.startswith("auto_null")]
            source = source or audio.pick_default_source(candidates)
            if not source or not any(item.name == source for item in candidates):
                raise ValueError("Geen geldige audio-input beschikbaar. Controleer de USB-aansluiting.")
            if not any(item.name == sink and audio.is_airplay_sink(item) for item in audio.list_sinks()):
                raise ValueError("Deze speaker is niet beschikbaar als AirPlay-audio-uitgang. Vernieuw de apparaten.")
            unit, processing = self._prepare_filter(self.eq_settings, sink)
            try:
                loopback = audio.start_loopback(source, processing or sink, latency_ms)
            except RuntimeError:
                self._cleanup()
                raise
            self.state = replace(self.state, source=source, sink=sink, latency_ms=latency_ms,
                                 loopback_module=loopback, raop_module=raop_module, running=True)
            self._activate_filter(unit, processing, self.eq_settings.preset)
            self.stream_warning = None
            self._persist()
            logger.info("Stream started: %s -> %s (EQ %s, module %s)", source, sink, bool(unit), loopback)
            return self._snapshot()

    def disconnect(self) -> dict:
        with self.lock:
            if self._reconcile():
                audio.stop_loopback(self.state.loopback_module)
            self.state.running = False
            self.state.loopback_module = None
            self._queue_cleanup(self.state.eq_unit)
            self._clear_filter()
            self.stream_warning = None
            self._persist()
            self._cleanup()
            logger.info("Stream stopped")
            return self._snapshot()

    def configure_equalizer(self, enabled: bool, preset: str) -> dict:
        desired = equalizer.Settings(enabled, preset)
        with self.lock:
            self._reconcile()
            if enabled and not self.engine.available():
                raise RuntimeError("Equaliser vereist PipeWire en een systemd-gebruikerssessie op de Pi.")
            needs_route = self.state.running and (
                enabled != bool(self.state.eq_unit) or enabled and preset != self.state.eq_preset
            )
            if needs_route:
                self._switch_route(desired)
            self.eq_settings = desired
            self._save_preferences()
            self._cleanup()
            return self.status()

    def _switch_route(self, desired: equalizer.Settings) -> None:
        if not any(item.name == self.state.sink for item in audio.list_sinks()):
            raise RuntimeError("De actieve speaker is niet beschikbaar.")
        unit, processing = self._prepare_filter(desired, self.state.sink)
        old = replace(self.state, eq_cleanup=list(self.state.eq_cleanup))
        try:
            audio.stop_loopback(old.loopback_module)
        except RuntimeError:
            self._cleanup()
            raise
        try:
            loopback = audio.start_loopback(old.source, processing or old.sink, old.latency_ms)
        except RuntimeError as exc:
            try:
                restored = audio.start_loopback(old.source, old.eq_sink or old.sink, old.latency_ms)
                self.state.loopback_module = restored
            except RuntimeError:
                self.state.running = False
                self.state.loopback_module = None
                self._queue_cleanup(old.eq_unit)
                self._clear_filter()
                self.stream_warning = "De vorige audiostream kon niet worden hersteld. Start streaming opnieuw."
            self._persist()
            self._cleanup()
            raise RuntimeError("De equaliser kon niet worden toegepast. " +
                               ("De vorige audiostream is hersteld." if self.state.running else self.stream_warning)) from exc
        self.state.loopback_module = loopback
        self._activate_filter(unit, processing, desired.preset)
        self._queue_cleanup(old.eq_unit)
        self._persist()
        # Speaker volume/mute are untouched: only the processing route changes.

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
