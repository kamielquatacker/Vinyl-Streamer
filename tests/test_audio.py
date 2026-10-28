import subprocess
from unittest.mock import patch

import pytest

from app import audio


@pytest.mark.parametrize("separator", ["\t", "    "])
def test_audio_format_and_state_stay_in_their_columns(separator):
    row = separator.join(["79", "alsa_input.usb-capture", "PipeWire", "s16le 2ch 44100Hz", "RUNNING"])
    item, = audio._parse_items(row)
    assert item.format == "s16le 2ch 44100Hz"
    assert item.state == "RUNNING"


@pytest.mark.parametrize("error, expected", [
    (FileNotFoundError(), "pactl ontbreekt"),
    (subprocess.TimeoutExpired("pactl", 5), "niet op tijd"),
    (PermissionError(), "niet worden uitgevoerd"),
])
def test_audio_errors_are_actionable(error, expected):
    with patch.object(audio.subprocess, "run", side_effect=error):
        with pytest.raises(RuntimeError, match=expected):
            audio.list_sinks()


def test_recycled_module_id_is_not_our_stream():
    assert not audio.is_stream_module(audio.AudioModule("100", "module-null-sink", ""), "usb", "bose")
    assert not audio.is_stream_module(audio.AudioModule("100", "module-loopback", "source=other sink=bose"), "usb", "bose")


def test_loopback_is_not_moved_to_another_device():
    with patch.object(audio, "_run", return_value="100") as run:
        audio.start_loopback("usb", "bose", 80)
    assert "source_dont_move=true" in run.call_args.args[0]
    assert "sink_dont_move=true" in run.call_args.args[0]
