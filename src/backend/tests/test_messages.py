"""The WebSocket messages and their JSON Schema (docs/backend.md 9)."""

import json

import pytest
from pydantic import ValidationError

from dod.api import messages as m
from dod.api.schema import FILE, build
from dod.bus import Bus
from dod.settings import Settings
from dod.state import State

GOOD = [
    {"type": "join_queue"},
    {"type": "leave_queue"},
    {"type": "set_preset", "preset": "fire"},
    {"type": "set_param", "name": "speed", "value": 1.5},
    {"type": "set_param", "name": "fade", "value": True},
    {"type": "set_param", "name": "color", "value": "#ff8000"},
    {"type": "set_matrix", "mode": "drawing", "drawing": "183C7EFFFF7E3C18"},
    {"type": "set_matrix", "mode": "icon"},
    {"type": "play_song", "song": "dQw4w9WgXcQ"},
    {"type": "loading_started"},
    {"type": "spectrum", "bands": [0.5] * 32, "beat": True},
    {"type": "player", "song": "dQw4w9WgXcQ", "position": 12.5, "ended": False},
    {"type": "admin", "action": "skip"},
]

BAD = [
    "not json",
    "[]",
    "{}",
    {"type": "dance"},
    {"type": "join_queue", "extra": 1},  # unknown fields are refused, typos don't pass silently
    {"type": "set_preset"},
    {"type": "set_preset", "preset": ""},
    {"type": "set_preset", "preset": "x" * 41},
    {"type": "set_param", "name": "speed", "value": [1]},
    {"type": "set_param", "name": "speed", "value": None},
    {"type": "set_matrix", "mode": "paint"},
    {"type": "set_matrix", "mode": "drawing", "drawing": "183c"},
    {"type": "play_song", "song": "../../etc/passwd"},
    {"type": "spectrum", "bands": [0.5] * 31},
    {"type": "spectrum", "bands": [1.5] + [0.5] * 31},
    {"type": "player", "song": "dQw4w9WgXcQ", "position": -1},
    {"type": "admin", "action": "self_destruct"},
]


@pytest.mark.parametrize("message", GOOD, ids=lambda d: d["type"])
def test_every_message_parses(message):
    parsed = m.parse(json.dumps(message))
    assert parsed.type == message["type"]


@pytest.mark.parametrize("message", BAD, ids=str)
def test_unknown_and_malformed_messages_are_refused(message):
    with pytest.raises(ValidationError):
        m.parse(message if isinstance(message, str) else json.dumps(message))


def test_param_values_keep_their_type():
    assert m.parse('{"type": "set_param", "name": "a", "value": true}').value is True
    assert m.parse('{"type": "set_param", "name": "a", "value": 2}').value == 2.0
    assert m.parse('{"type": "set_param", "name": "a", "value": "#ff0000"}').value == "#ff0000"


def test_the_state_fits_its_message():
    state = State(Settings(), Bus())
    state.join("aaaa11112222")
    state.song_started("dQw4w9WgXcQ", "Song", 213, by="aaaa11112222")
    message = m.StateMessage.model_validate({"type": "state", **state.to_dict()})
    assert message.music.playing and message.queue.controller == "aaaa"
    you = m.You.model_validate({"type": "you", **state.you("aaaa11112222")})
    assert you.in_control


def test_the_schema_file_is_up_to_date():
    assert FILE.exists(), "run ./dod schema"
    assert FILE.read_text(encoding="utf-8") == build(), "the messages changed: run ./dod schema"


def test_the_schema_lists_every_message_with_its_type_required():
    schema = json.loads(build())
    incoming = {ref["$ref"].split("/")[-1] for ref in schema["properties"]["incoming"]["oneOf"]}
    outgoing = {ref["$ref"].split("/")[-1] for ref in schema["properties"]["outgoing"]["oneOf"]}
    assert len(incoming) == 10 and "SetMatrix" in incoming
    assert outgoing == {"Welcome", "StateMessage", "You", "Preview", "Log", "Error"}
    for name in incoming | outgoing:
        assert "type" in schema["$defs"][name]["required"], name  # the frontend tells them apart by type
    assert "drawing" not in schema["$defs"]["SetMatrix"]["required"]  # optional when sent by a browser
