import json
from unittest.mock import patch

import pytest

from app import audio, controller, equalizer, state


def start(backend):
    return backend.controller.connect(None, backend.sinks[0].name, 80)


def test_disabled_equalizer_keeps_original_route(backend):
    start(backend)
    assert backend.starts[0][1] == backend.sinks[0].name
    assert not backend.eq_starts


def test_preferences_survive_restart_without_starting_audio(backend):
    backend.controller.configure_equalizer(True, "warm")
    assert not backend.eq_starts
    state.STATE_PATH.unlink(missing_ok=True)
    restored = controller.StreamController()
    assert restored.eq_settings == equalizer.Settings(True, "warm")
    assert not restored.state.running


def test_enabled_equalizer_routes_stereo_and_keeps_volume_on_speaker(backend):
    backend.controller.configure_equalizer(True, "warm")
    start(backend)
    status = backend.controller.status()
    assert status["equalizer"]["active"]
    assert backend.starts[0][1] == status["eq_sink"]
    assert status["sink"] == backend.eq_starts[0][1]
    assert -3 < status["equalizer"]["preamp_db"] < -2
    backend.controller.set_volume(volume=45)
    assert backend.volumes == [(status["sink"], 45)]


def test_live_preset_change_and_disable_leave_only_one_route(backend):
    backend.controller.configure_equalizer(True, "warm")
    start(backend)
    first_unit = backend.controller.state.eq_unit
    changed = backend.controller.configure_equalizer(True, "bass")
    assert changed["equalizer"]["preset"] == "bass"
    assert changed["eq_unit"] != first_unit
    assert first_unit in backend.eq_stops
    assert len(backend.modules) == 1
    assert not backend.volumes and not backend.mutes
    direct = backend.controller.configure_equalizer(False, "bass")
    assert direct["eq_unit"] is None and direct["running"]
    assert backend.starts[-1][1] == direct["sink"]
    assert not any(item.name.startswith("vinyl_eq.") for item in backend.sinks)


def test_failed_filter_start_does_not_interrupt_current_stream(backend, monkeypatch):
    start(backend)
    original = backend.controller.state.loopback_module
    original_start = backend.controller.engine.start

    def fail(unit, target, preset):
        original_start(unit, target, preset)
        raise RuntimeError("Filter failed")
    monkeypatch.setattr(backend.controller.engine, "start", fail)
    with pytest.raises(RuntimeError, match="Filter failed"):
        backend.controller.configure_equalizer(True, "warm")
    assert backend.controller.state.loopback_module == original
    assert not backend.stops
    assert not backend.controller.eq_settings.enabled
    assert backend.eq_stops and not backend.controller.state.eq_cleanup


def test_failed_new_route_restores_original_stream(backend, monkeypatch):
    start(backend)
    original_start = audio.start_loopback
    attempts = []

    def fail_first(*args):
        attempts.append(args)
        if len(attempts) == 1:
            raise RuntimeError("Cannot connect")
        return original_start(*args)
    monkeypatch.setattr(audio, "start_loopback", fail_first)
    with pytest.raises(RuntimeError, match="vorige audiostream is hersteld"):
        backend.controller.configure_equalizer(True, "warm")
    assert backend.controller.status()["running"]
    assert len(backend.modules) == 1
    assert backend.modules[0].id == backend.controller.state.loopback_module
    assert not backend.controller.eq_settings.enabled
    assert not backend.controller.state.eq_cleanup


def test_failed_rollback_reports_stopped_stream(backend, monkeypatch):
    backend.controller.configure_equalizer(True, "warm")
    start(backend)
    monkeypatch.setattr(audio, "start_loopback", lambda *args: (_ for _ in ()).throw(RuntimeError("Cannot connect")))
    with pytest.raises(RuntimeError, match="niet worden hersteld"):
        backend.controller.configure_equalizer(True, "bass")
    assert not backend.controller.state.running
    assert backend.controller.state.loopback_module is None
    assert backend.controller.state.eq_unit is None
    assert len(backend.eq_stops) == 2


def test_stop_failure_preserves_filter_and_stream(backend, monkeypatch):
    backend.controller.configure_equalizer(True, "warm")
    start(backend)
    monkeypatch.setattr(audio, "stop_loopback", lambda _: (_ for _ in ()).throw(RuntimeError("Stop failed")))
    with pytest.raises(RuntimeError):
        backend.controller.disconnect()
    assert backend.controller.state.eq_unit
    assert not backend.eq_stops
    assert backend.controller.state.running


def test_cleanup_failure_is_retried_after_api_restart(backend, monkeypatch):
    backend.controller.configure_equalizer(True, "warm")
    start(backend)
    stop = backend.controller.engine.stop
    monkeypatch.setattr(backend.controller.engine, "stop", lambda _: (_ for _ in ()).throw(RuntimeError("Busy")))
    response = backend.controller.disconnect()
    assert not response["running"] and response["warnings"]
    assert response["eq_cleanup"]
    restored = controller.StreamController()
    restored.status()
    assert not restored.state.eq_cleanup
    assert backend.eq_stops
    monkeypatch.setattr(backend.controller.engine, "stop", stop)


def test_running_equalizer_is_recognized_after_api_restart(backend):
    backend.controller.configure_equalizer(True, "warm")
    start(backend)
    restored = controller.StreamController()
    result = restored.status()
    assert result["running"] and result["equalizer"]["active"]
    restored.disconnect()
    assert not backend.modules and backend.eq_stops


def test_missing_filter_can_be_recovered_by_disabling_eq(backend):
    backend.controller.configure_equalizer(True, "warm")
    start(backend)
    backend.sinks[:] = [item for item in backend.sinks if not item.name.startswith("vinyl_eq.")]
    status = backend.controller.status()
    assert not status["equalizer"]["active"] and status["warnings"]
    status = backend.controller.configure_equalizer(False, "warm")
    assert status["running"] and status["eq_unit"] is None


def test_preferences_write_failure_does_not_lose_active_stream(backend, monkeypatch):
    start(backend)
    monkeypatch.setattr(equalizer, "save_settings", lambda _: (_ for _ in ()).throw(OSError("Disk full")))
    status = backend.controller.configure_equalizer(True, "warm")
    assert status["running"] and status["equalizer"]["active"]
    assert status["warnings"]
    backend.controller.disconnect()
    assert not backend.modules


def test_configuration_has_separate_stereo_filters_and_no_speaker_fallback():
    unit = equalizer.new_unit()
    config = equalizer.filter_config(unit, "raop_sink.bose", "bass")
    args = config["context.modules"][-1]["args"]
    graph = args["filter.graph"]
    assert len(graph["inputs"]) == len(graph["outputs"]) == 2
    assert len(graph["nodes"]) == 12
    assert len(graph["links"]) == 10
    assert args["playback.props"]["target.object"] == "raop_sink.bose"
    assert args["playback.props"]["node.dont-fallback"]
    assert args["playback.props"]["node.dont-reconnect"]
    assert all(node["control"]["Mult"] <= 1 for node in graph["nodes"] if node["label"] == "linear")
    assert equalizer.preamp_db("neutral") == 0


def test_engine_rejects_unrelated_service_names(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    with patch.object(audio, "_run") as run:
        with pytest.raises(ValueError):
            equalizer.EqualizerEngine().stop("pipewire.service")
        run.assert_not_called()


def test_engine_refuses_to_stop_unit_with_mismatched_command(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    with patch.object(audio, "_run", side_effect=["loaded", "/usr/bin/unrelated"]) as run:
        with pytest.raises(RuntimeError, match="niet overeen"):
            equalizer.EqualizerEngine().stop(equalizer.new_unit())
        assert all("stop" not in call.args[0] for call in run.call_args_list)


@pytest.mark.parametrize("data", [{"enabled": "yes"}, {"enabled": True, "preset": "unknown"}, {"preset": []}])
def test_bad_preferences_default_to_bypass(backend, data):
    equalizer.SETTINGS_PATH.write_text(json.dumps(data))
    assert equalizer.load_settings() == equalizer.Settings()


def test_bad_runtime_eq_identity_is_not_used(backend):
    state.STATE_PATH.write_text(json.dumps({"eq_unit": "pipewire.service", "eq_sink": "speaker", "eq_preset": "warm"}))
    assert state.load_state() == state.StreamState()



def test_native_engine_waits_for_stable_active_sink(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    engine = equalizer.EqualizerEngine()
    monkeypatch.setattr(engine, "available", lambda: True)
    monkeypatch.setattr(equalizer.shutil, "which", lambda _: "/usr/bin/pipewire")
    monkeypatch.setattr(equalizer.time, "sleep", lambda _: None)
    unit = equalizer.new_unit()
    monkeypatch.setattr(audio, "list_sinks", lambda: [type("Sink", (), {"name": equalizer.processing_sink(unit)})()])
    calls = []

    def run(command):
        calls.append(command)
        if command == ["pipewire", "--version"]:
            return "Linked with libpipewire 1.2.7"
        return "active"

    monkeypatch.setattr(audio, "_run", run)
    assert engine.start(unit, "raop_sink.bose", "warm") == equalizer.processing_sink(unit)
    assert sum("--property=ActiveState" in call for call in calls) == 2
    assert any("--collect" in call for call in calls)
    name = equalizer.processing_sink(unit)
    assert ["pactl", "set-sink-volume", name, "100%"] in calls
    assert ["pactl", "set-sink-mute", name, "0"] in calls
    config = engine.config_path(unit).read_text()
    assert '"target.object" = "raop_sink.bose"' in config
    assert '"Mult" =' in config


def test_native_engine_rejects_unsupported_pipewire_before_start(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    engine = equalizer.EqualizerEngine()
    monkeypatch.setattr(engine, "available", lambda: True)
    with patch.object(audio, "_run", return_value="Linked with libpipewire 0.3.65") as run:
        with pytest.raises(RuntimeError, match="1.2"):
            engine.start(equalizer.new_unit(), "raop_sink.bose", "warm")
        assert run.call_count == 1


def test_native_engine_cleanup_of_collected_unit_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    engine = equalizer.EqualizerEngine()
    unit = equalizer.new_unit()
    path = engine.config_path(unit)
    path.parent.mkdir()
    path.write_text("test")
    with patch.object(audio, "_run", return_value="") as run:
        engine.stop(unit)
        engine.stop(unit)
        assert not path.exists()
        assert all("stop" not in call.args[0] for call in run.call_args_list)



def test_custom_bands_survive_restart_and_preset_roundtrip(backend):
    bands = [3, 1, -2, 0.5, -1]
    backend.controller.configure_equalizer(True, "custom", bands)
    start(backend)
    restored = controller.StreamController()
    assert restored.status()["equalizer"]["bands"] == bands
    original = restored.state.eq_unit
    restored.configure_equalizer(True, "custom", [2, 1, -2, 0.5, -1])
    assert restored.state.eq_unit != original
    restored.configure_equalizer(True, "warm")
    restored.configure_equalizer(True, "custom")
    assert restored.status()["equalizer"]["bands"] == [2, 1, -2, 0.5, -1]
    assert len(backend.modules) == 1
    assert not backend.volumes and not backend.mutes


def test_custom_route_failure_preserves_old_bands(backend, monkeypatch):
    bands = [1, 0, -1, 0, 0]
    backend.controller.configure_equalizer(True, "custom", bands)
    start(backend)
    original = audio.start_loopback
    def fail_new(source, sink, latency):
        if sink != backend.controller.state.eq_sink:
            raise RuntimeError("Cannot connect")
        return original(source, sink, latency)
    monkeypatch.setattr(audio, "start_loopback", fail_new)
    with pytest.raises(RuntimeError):
        backend.controller.configure_equalizer(True, "custom", [2, 0, 0, 0, 0])
    status = backend.controller.status()
    assert status["equalizer"]["bands"] == bands
    assert status["eq_bands"] == bands and status["running"]


def test_old_preferences_remain_compatible(backend):
    equalizer.SETTINGS_PATH.write_text('{"enabled": true, "preset": "warm"}')
    assert equalizer.load_settings() == equalizer.Settings(True, "warm")


@pytest.mark.parametrize("bands", [[0]*4, [0]*6, [7,0,0,0,0], [float("nan")]*5, [True]*5, "invalid"])
def test_invalid_custom_bands_rejected(bands):
    with pytest.raises(ValueError):
        equalizer.Settings(True, "custom", bands)


def test_headroom_uses_combined_response_instead_of_summing_boosts():
    assert equalizer.preamp_db("custom", [0]*5) == 0
    assert equalizer.preamp_db("custom", [-6]*5) == 0
    assert equalizer.preamp_db("custom", [0,0,6,0,0]) == -6.2
    assert -15 < equalizer.preamp_db("custom", [6]*5) < -6
    assert equalizer.preamp_db("voices") > -3


def test_custom_graph_uses_requested_bands_on_both_channels():
    bands = [-2, 1, 3, -1, 0.5]
    args = equalizer.filter_config(equalizer.new_unit(), "raop_sink.bose", "custom", bands)["context.modules"][-1]["args"]
    graph = args["filter.graph"]
    assert [node["control"]["Gain"] for node in graph["nodes"] if node["label"] == "bq_peaking"] == bands * 2
