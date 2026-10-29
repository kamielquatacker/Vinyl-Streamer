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


def test_home_screen_manifest_and_icons_are_valid(client):
    import struct

    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    manifest = response.json()
    assert manifest["name"] == "Vinyl Streamer"
    assert manifest["id"] == manifest["start_url"] == manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert any(icon.get("purpose") == "maskable" for icon in manifest["icons"])
    assert {"192x192", "512x512"} <= {icon["sizes"] for icon in manifest["icons"]}
    for icon in manifest["icons"]:
        image = client.get(icon["src"])
        assert image.status_code == 200
        assert image.content[:8] == bytes.fromhex("89504e470d0a1a0a")
        width, height = struct.unpack(">II", image.content[16:24])
        assert f"{width}x{height}" == icon["sizes"]


def test_apple_icon_and_browser_favicon_are_served(client):
    import struct

    apple = client.get("/apple-touch-icon.png")
    assert apple.status_code == 200
    assert apple.headers["content-type"] == "image/png"
    assert struct.unpack(">II", apple.content[16:24]) == (180, 180)
    favicon = client.get("/favicon.ico")
    assert favicon.status_code == 200
    assert favicon.content[:6] == bytes.fromhex("000001000100")


def test_equalizer_settings_apply_and_invalid_presets_are_rejected(client, backend):
    response = client.post("/api/equalizer", json={"enabled": True, "preset": "warm"})
    assert response.status_code == 200
    assert response.json()["equalizer"]["enabled"]
    assert not response.json()["equalizer"]["active"]
    assert client.post("/api/equalizer", json={"enabled": True, "preset": "unknown"}).status_code == 422
    assert client.post("/api/connect", json={"sink": backend.sinks[0].name}).status_code == 200
    status = client.get("/api/status").json()
    assert status["equalizer"]["active"] and status["equalizer"]["preset"] == "warm"
    assert status["volume"] == 37
    assert client.post("/api/disconnect").status_code == 200
    assert backend.eq_stops



@pytest.mark.parametrize("bands", [[0]*5, [0]*7, [10.1,0,0,0,0,0], [0,0,-10.1,0,0,0], ["invalid"]*6])
def test_invalid_custom_bands_return_validation_error(client, bands):
    response = client.post("/api/equalizer", json={"enabled": True, "preset": "custom", "bands": bands})
    assert response.status_code == 422


def test_custom_bands_are_returned_by_api(client):
    bands = [10, -10, 0, 0.5, -2, 1]
    response = client.post("/api/equalizer", json={"enabled": False, "preset": "custom", "bands": bands})
    assert response.status_code == 200
    assert response.json()["equalizer"]["bands"] == bands



@pytest.mark.parametrize("preset", ["custom", "neutral", "warm", "bass", "clear", "voices"])
def test_all_equalizer_choices_remain_selectable(client, preset):
    response = client.post("/api/equalizer", json={"enabled": False, "preset": preset})
    assert response.status_code == 200
    assert response.json()["equalizer"]["preset"] == preset
