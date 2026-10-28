from unittest.mock import patch

import pytest

from app import state


def test_atomic_write_failure_preserves_previous_state(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setattr(state, "STATE_PATH", path)
    original = state.StreamState(sink="bose")
    state.save_state(original)
    with patch.object(state.os, "replace", side_effect=OSError("Disk full")):
        with pytest.raises(OSError):
            state.save_state(state.StreamState(sink="other"))
    assert state.load_state() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("content", ['{broken', '{"running": "yes"}', '{"latency_ms": -1}', '{"sink": 12}'])
def test_invalid_saved_state_is_ignored(tmp_path, monkeypatch, content):
    path = tmp_path / "state.json"
    path.write_text(content)
    monkeypatch.setattr(state, "STATE_PATH", path)
    assert state.load_state() == state.StreamState()
