import pytest
from fastapi.testclient import TestClient

from app import api, audio


@pytest.fixture
def client(backend, monkeypatch):
    monkeypatch.setattr(api, "controller", backend.controller)
    monkeypatch.setattr(api.discovery, "start", lambda: None)
    monkeypatch.setattr(api.discovery, "stop", lambda: None)
    with TestClient(api.app) as client:
        yield client


def test_status_includes_real_volume_and_mute(client, backend):
    response = client.post("/api/connect", json={"sink": backend.sinks[0].name})
    assert response.status_code == 200
    status = client.get("/api/status").json()
    assert status["volume"] == 37
    assert status["muted"] is True


def test_mute_and_volume_control_active_stream(client, backend):
    client.post("/api/connect", json={"sink": backend.sinks[0].name})
    assert client.post("/api/mute", json={"muted": False}).status_code == 200
    assert client.post("/api/volume", json={"volume": 55}).status_code == 200
    assert backend.mutes == [(backend.sinks[0].name, False)]
    assert backend.volumes == [(backend.sinks[0].name, 55)]
    assert client.post("/api/volume", json={"sink": "raop_sink.other", "volume": 10}).status_code == 409


def test_connect_conflict_is_an_actionable_response(client, backend):
    body = {"sink": backend.sinks[0].name}
    assert client.post("/api/connect", json=body).status_code == 200
    response = client.post("/api/connect", json=body)
    assert response.status_code == 409
    assert "al een stream actief" in response.json()["detail"]


@pytest.mark.parametrize("path, body", [
    ("/api/connect", {"sink": ""}),
    ("/api/connect", {"sink": "bose", "latency_ms": 0}),
    ("/api/connect", {"sink": "bose", "latency_ms": 501}),
    ("/api/volume", {"volume": -1}),
    ("/api/volume", {"volume": 151}),
])
def test_invalid_input_is_rejected(client, path, body):
    assert client.post(path, json=body).status_code == 422


def test_audio_failure_is_structured(client, monkeypatch):
    monkeypatch.setattr(audio, "list_modules", lambda: (_ for _ in ()).throw(RuntimeError("Audioserver offline")))
    response = client.get("/api/status")
    assert response.status_code == 503
    assert response.json()["detail"] == "Audioserver offline"


def test_discovery_warning_does_not_hide_network_devices(client, monkeypatch):
    monkeypatch.setattr(audio, "ensure_raop_module", lambda: (_ for _ in ()).throw(RuntimeError("RAOP ontbreekt")))
    response = client.get("/api/devices")
    assert response.status_code == 200
    assert "RAOP ontbreekt" in response.json()["warnings"][0]


def test_interface_and_assets_are_served(client):
    assert 'lang="nl"' in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


@pytest.mark.parametrize("name, driver", [
    ("raop_output.bose.local", "module-raop-sink.c"),
    ("custom-bose", "module-raop-sink.c"),
])
def test_pulseaudio_outputs_are_listed_and_selectable(client, backend, name, driver):
    backend.sinks[:] = [audio.AudioItem("2", name, driver, "s16le 2ch 44100Hz", "IDLE")]
    response = client.get("/api/devices")
    assert response.json()["sinks"][0]["name"] == name
    assert client.post("/api/connect", json={"sink": name}).status_code == 200
