from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app import audio, controller


def connect(backend):
    return backend.controller.connect(None, backend.sinks[0].name, 80)


def test_two_simultaneous_connects_create_only_one_loopback(backend):
    barrier = Barrier(2)

    def attempt():
        barrier.wait()
        try:
            connect(backend)
            return "started"
        except controller.StreamConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == ["conflict", "started"]
    assert len(backend.starts) == 1


def test_status_detects_audio_server_restart_and_keeps_warning(backend):
    connect(backend)
    backend.modules.clear()
    assert not backend.controller.status()["running"]
    assert backend.controller.status()["warnings"]
    connect(backend)
    assert not backend.controller.status()["warnings"]


def test_disconnect_failure_keeps_stream_for_retry(backend, monkeypatch):
    connect(backend)
    stop = audio.stop_loopback
    monkeypatch.setattr(audio, "stop_loopback", lambda _: (_ for _ in ()).throw(RuntimeError("Stop failed")))
    with pytest.raises(RuntimeError, match="Stop failed"):
        backend.controller.disconnect()
    assert backend.controller.state.running
    assert backend.controller.state.loopback_module == "100"
    monkeypatch.setattr(audio, "stop_loopback", stop)
    assert not backend.controller.disconnect()["running"]


def test_disconnect_does_not_unload_recycled_module(backend):
    connect(backend)
    backend.modules[:] = [audio.AudioModule("100", "module-null-sink", "")]
    backend.controller.disconnect()
    assert not backend.stops


def test_volume_targets_active_sink_and_rejects_stale_selection(backend):
    connect(backend)
    backend.controller.set_volume(volume=60, muted=False)
    assert backend.volumes == [(backend.sinks[0].name, 60)]
    assert backend.mutes == [(backend.sinks[0].name, False)]
    with pytest.raises(controller.StreamConflict):
        backend.controller.set_volume(volume=50, sink="raop_sink.other")


def test_volume_requires_active_stream(backend):
    with pytest.raises(controller.StreamConflict):
        backend.controller.set_volume(volume=50)


def test_failed_persistence_does_not_lose_running_stream(backend, monkeypatch):
    monkeypatch.setattr(controller, "save_state", lambda _: (_ for _ in ()).throw(OSError("Disk full")))
    result = connect(backend)
    assert result["running"] and result["warnings"]
    assert backend.controller.state.loopback_module == "100"
    backend.controller.disconnect()
    assert backend.stops == ["100"]


def test_restored_stream_is_verified_and_controllable(backend):
    connect(backend)
    restored = controller.StreamController()
    assert restored.status()["running"]
    restored.disconnect()
    assert backend.stops == ["100"]


def test_missing_source_is_reported_without_losing_stop_control(backend):
    connect(backend)
    backend.sources.clear()
    status = backend.controller.status()
    assert status["running"] and status["warnings"]
    backend.controller.disconnect()
    assert backend.stops == ["100"]


def test_invalid_device_does_not_start_loopback(backend):
    with pytest.raises(ValueError):
        backend.controller.connect(None, "not-a-speaker", 80)
    assert not backend.starts
