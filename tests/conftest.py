from types import SimpleNamespace

import pytest

from app import audio, controller, equalizer, state


@pytest.fixture
def backend(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(equalizer, "SETTINGS_PATH", tmp_path / "equalizer.json")
    fake = SimpleNamespace(
        modules=[], starts=[], stops=[], volumes=[], mutes=[], eq_starts=[], eq_stops=[],
        sources=[audio.AudioItem("1", "alsa_input.usb-capture", "PipeWire", "s16le 2ch 44100Hz", "RUNNING")],
        sinks=[audio.AudioItem("2", "raop_sink.192.168.1.20", "PipeWire", "s16le 2ch 44100Hz", "IDLE")],
    )

    def start(source, sink, latency):
        module_id = str(100 + len(fake.starts))
        fake.starts.append((source, sink, latency))
        fake.modules.append(audio.AudioModule(module_id, "module-loopback", f"source={source} sink={sink} latency_msec={latency}"))
        return module_id

    def stop(module_id):
        fake.stops.append(module_id)
        fake.modules[:] = [item for item in fake.modules if item.id != module_id]

    monkeypatch.setattr(audio, "list_modules", lambda: list(fake.modules))
    monkeypatch.setattr(audio, "list_sources", lambda: list(fake.sources))
    monkeypatch.setattr(audio, "list_sinks", lambda: list(fake.sinks))
    monkeypatch.setattr(audio, "ensure_raop_module", lambda: "50")
    monkeypatch.setattr(audio, "start_loopback", start)
    monkeypatch.setattr(audio, "stop_loopback", stop)
    monkeypatch.setattr(audio, "get_sink_volume", lambda sink: 37)
    monkeypatch.setattr(audio, "get_sink_mute", lambda sink: True)
    monkeypatch.setattr(audio, "set_sink_volume", lambda sink, volume: fake.volumes.append((sink, volume)))
    monkeypatch.setattr(audio, "set_sink_mute", lambda sink, muted: fake.mutes.append((sink, muted)))
    class FakeEngine:
        def available(self):
            return True

        def start(self, unit, target, preset, bands=None):
            fake.eq_starts.append((unit, target, preset))
            name = equalizer.processing_sink(unit)
            fake.sinks.append(audio.AudioItem("90", name, "PipeWire", "float32le 2ch 44100Hz", "RUNNING"))
            return name

        def stop(self, unit):
            fake.eq_stops.append(unit)
            name = equalizer.processing_sink(unit)
            fake.sinks[:] = [item for item in fake.sinks if item.name != name]

    monkeypatch.setattr(equalizer, "EqualizerEngine", FakeEngine)
    fake.controller = controller.StreamController()
    return fake
