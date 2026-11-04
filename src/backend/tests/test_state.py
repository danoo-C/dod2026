"""The stand's state (docs/backend.md 6), with a fake clock."""

import pytest

from dod.bus import (
    Bus,
    DrawingChanged,
    ParamChanged,
    PresetChanged,
    SongEnded,
    SongStarted,
    TurnEnded,
    TurnStarted,
)
from dod.control.sessions import MAIN
from dod.settings import Settings
from dod.state import State

A, B = "aaaa11112222", "bbbb33334444"  # public ids


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Rig:
    def __init__(self, **settings):
        self.clock = Clock()
        self.bus = Bus()
        self.events = self.bus.subscribe(size=1000)
        self.state = State(Settings(**settings), self.bus, clock=self.clock, wall=lambda: self.clock.t + 1e9)
        self.changes = 0
        self.state.on_change(lambda s: setattr(self, "changes", self.changes + 1))

    def at(self, t):
        self.clock.t = 1000.0 + t
        self.state.tick()

    def taken(self, kind=None):
        events = self.events.take_all()
        return [e for e in events if kind is None or isinstance(e, kind)]


def with_controller(**settings):
    rig = Rig(**settings)
    rig.state.connected(A)
    rig.state.join(A)
    rig.taken()
    rig.changes = 0
    return rig


# --- the start --------------------------------------------------------------------


def test_it_starts_idle_with_the_rainbow_ready():
    s = Rig().state
    assert s.mode == "idle" and s.preset == "rainbow" and s.params["speed"] == 0.3
    assert s.queue.controller is None and not s.playing


def test_the_state_for_the_pages():
    rig = with_controller()
    d = rig.state.to_dict()
    assert d["now"] == pytest.approx(1e9 + 1000)
    assert d["mode"] == "idle"
    assert d["manual"] == {"preset": "rainbow", "params": rig.state.params, "matrix": "icon",
                           "drawing": "0000000000000000"}
    assert d["music"] == {"song": None, "title": None, "started_at": None, "length": None, "playing": False,
                          "player_connected": False}
    assert d["queue"] == {"controller": "aaaa", "turn_ends_at": pytest.approx(1e9 + 1000 + 180),
                          "turn_over": False, "waiting": 0, "paused": False}
    assert d["hardware"]["state"] == "connecting"


def test_you():
    rig = with_controller()
    rig.state.connected(B)
    rig.state.join(B)
    assert rig.state.you(A) == {"session": "aaaa", "position": 0, "in_control": True,
                                "turn_ends_at": pytest.approx(1e9 + 1000 + 180)}
    assert rig.state.you(B) == {"session": "bbbb", "position": 1, "in_control": False, "turn_ends_at": None}
    assert rig.state.you("cccc55556666")["position"] is None


# --- permissions --------------------------------------------------------------------


def test_who_may_control():
    rig = with_controller()
    assert rig.state.may_control(A) and rig.state.may_control(MAIN)
    assert not rig.state.may_control(B)


# --- presets and parameters ---------------------------------------------------------


def test_picking_a_preset():
    rig = with_controller()
    rig.state.set_preset("solid", by=A)
    assert rig.state.mode == "manual" and rig.state.preset == "solid"
    [event] = rig.taken(PresetChanged)
    assert (event.preset, event.by) == ("solid", "aaaa")  # the short id, for the logs


def test_an_unknown_preset_changes_nothing():
    rig = with_controller()
    with pytest.raises(ValueError):
        rig.state.set_preset("disco", by=A)
    with pytest.raises(ValueError):
        rig.state.set_preset("idle", by=A)  # phones can't pick idle
    assert rig.changes == 0 and rig.taken() == []


def test_parameters_are_checked_and_remembered_per_preset():
    rig = with_controller()
    rig.state.set_preset("rainbow", by=A)
    rig.state.set_param("speed", 1.5, by=A)
    with pytest.raises(ValueError):
        rig.state.set_param("speed", 99, by=A)
    with pytest.raises(ValueError):
        rig.state.set_param("color", "#ff0000", by=A)  # solid's, not rainbow's
    rig.state.set_preset("solid", by=A)
    assert rig.state.params == rig.state._presets["solid"].defaults()
    rig.state.set_preset("rainbow", by=A)
    assert rig.state.params["speed"] == 1.5  # back to the rainbow as it was left
    [event] = rig.taken(ParamChanged)
    assert (event.preset, event.name, event.value) == ("rainbow", "speed", 1.5)


def test_the_drawing():
    rig = with_controller()
    rig.state.set_matrix("drawing", "183C7EFFFF7E3C18", by=A)
    assert rig.state.matrix_mode == "drawing" and rig.state.drawing == bytes.fromhex("183c7effff7e3c18")
    assert rig.state.to_dict()["manual"]["drawing"] == "183c7effff7e3c18"
    assert len(rig.taken(DrawingChanged)) == 1
    rig.state.set_matrix("icon", None, by=A)  # back to the icon, the drawing is kept
    assert rig.state.matrix_mode == "icon" and rig.state.drawing == bytes.fromhex("183c7effff7e3c18")
    for mode, drawing in (("paint", None), ("drawing", "183c"), ("drawing", "zz3c7effff7e3c18"), ("drawing", 5)):
        with pytest.raises(ValueError):
            rig.state.set_matrix(mode, drawing, by=A)


# --- notifications ------------------------------------------------------------------


def test_one_notification_per_change_and_none_without_one():
    rig = with_controller()
    rig.changes = 0
    rig.state.set_preset("solid", by=A)
    assert rig.changes == 1
    rig.state.set_preset("solid", by=A)  # the same again
    rig.state.set_param("fade", False, by=A)  # already False
    rig.state.tick()  # nothing due
    assert rig.changes == 1
    rig.state.set_param("fade", True, by=A)
    assert rig.changes == 2


def test_a_song_replaced_by_a_preset_is_one_notification():
    rig = with_controller()
    rig.state.song_started("dQw4w9WgXcQ", "Song", 213, by=A)
    rig.changes = 0
    rig.state.set_preset("solid", by=A)  # stops the song and switches the preset: still one change
    assert rig.changes == 1


# --- songs and modes ----------------------------------------------------------------


def test_a_song_switches_to_music_and_back_to_the_preset():
    rig = with_controller()
    rig.state.set_preset("solid", by=A)
    rig.state.song_started("dQw4w9WgXcQ", "Never Gonna", 213, by=A)
    assert rig.state.mode == "music"
    d = rig.state.to_dict()["music"]
    assert d["song"] == "dQw4w9WgXcQ" and d["playing"] and d["length"] == 213
    assert d["started_at"] == pytest.approx(1e9 + 1000)
    rig.state.song_ended("ended")
    assert rig.state.mode == "manual" and rig.state.preset == "solid" and not rig.state.playing
    [started] = rig.taken(SongStarted)
    assert started.by == "aaaa" and started.title == "Never Gonna"


def test_picking_a_preset_stops_the_song():
    rig = with_controller()
    rig.state.song_started("dQw4w9WgXcQ", "Song", 213, by=A)
    rig.state.set_preset("rainbow", by=A)
    assert rig.state.mode == "manual" and not rig.state.playing
    assert [e.reason for e in rig.taken(SongEnded)] == ["stopped"]


def test_another_song_replaces_the_first():
    rig = with_controller()
    rig.state.song_started("first000000", "One", 100, by=A)
    rig.state.song_started("second00000", "Two", 100, by=A)
    assert rig.state.song.song == "second00000" and rig.state.mode == "music"
    assert [e.reason for e in rig.taken(SongEnded)] == ["replaced"]


def test_the_controllers_song_ending_ends_the_turn_when_someone_waits():
    rig = with_controller()
    rig.state.connected(B)
    rig.state.join(B)
    rig.state.song_started("dQw4w9WgXcQ", "Song", 213, by=A)
    rig.taken()
    rig.state.song_ended("ended")
    assert rig.state.queue.controller == B
    assert [type(e) for e in rig.taken() if isinstance(e, (TurnEnded, TurnStarted))] == [TurnEnded, TurnStarted]


def test_a_stopped_song_doesnt_end_the_turn():
    rig = with_controller()
    rig.state.connected(B)
    rig.state.join(B)
    rig.state.song_started("dQw4w9WgXcQ", "Song", 213, by=A)
    rig.state.song_ended("stopped")
    assert rig.state.queue.controller == A


def test_bad_song_end_reason():
    with pytest.raises(ValueError):
        Rig().state.song_ended("bored")


# --- idle ---------------------------------------------------------------------------


def test_idle_after_nobody_plays_for_idle_seconds():
    rig = with_controller()
    rig.state.set_preset("solid", by=A)
    rig.at(29)  # A stops sending at t = 0: inactive at 30
    assert rig.state.queue.controller == A
    rig.at(30)
    assert rig.state.queue.controller is None and rig.state.mode == "manual"
    rig.at(59)
    assert rig.state.mode == "manual"
    rig.at(60)  # 30 s with nobody in control and nothing playing
    assert rig.state.mode == "idle"


def test_a_playing_song_keeps_idle_away():
    rig = Rig()
    rig.state.song_started("dQw4w9WgXcQ", "Song", 213, by=MAIN)  # the main screen, nobody in the queue
    rig.at(200)
    assert rig.state.mode == "music"
    rig.state.song_ended("ended")
    rig.at(229)
    assert rig.state.mode == "manual"
    rig.at(231)
    assert rig.state.mode == "idle"


def test_any_command_ends_idle():
    rig = Rig()
    assert rig.state.mode == "idle"
    rig.state.set_param("speed", 1.0, by=MAIN)
    assert rig.state.mode == "manual"
    rig.at(31)
    assert rig.state.mode == "idle"
    rig.state.set_matrix("drawing", "ff" * 8, by=MAIN)
    assert rig.state.mode == "manual"


def test_a_controller_keeps_idle_away():
    rig = with_controller(inactive_seconds=600)
    rig.state.set_preset("solid", by=A)
    rig.at(100)
    assert rig.state.mode == "manual"


def test_a_broken_preset_goes_idle():
    rig = with_controller()
    rig.state.set_preset("solid", by=A)
    rig.state.effect_failed("rainbow")  # not the one showing: nothing happens
    assert rig.state.mode == "manual"
    rig.state.effect_failed("solid")
    assert rig.state.mode == "idle"


# --- the queue through the state ----------------------------------------------------


def test_queue_commands_publish_their_events_and_notify():
    rig = Rig()
    rig.state.connected(A)
    rig.state.join(A)
    assert [type(e).__name__ for e in rig.taken()] == ["QueueJoined", "TurnStarted"]
    rig.state.connected(B)
    rig.state.join(B)
    rig.changes = 0
    rig.state.skip()
    assert rig.state.queue.controller == B and rig.changes == 1
    rig.state.pause_queue()
    assert rig.state.to_dict()["queue"]["paused"]
    rig.state.resume_queue()
    rig.state.leave(B)
    assert rig.state.queue.controller is None


def test_a_command_counts_as_activity():
    rig = with_controller()
    rig.at(25)
    rig.state.set_param("speed", 1.0, by=A)
    rig.at(50)
    assert rig.state.queue.controller == A  # 25 s since the command
    rig.state.set_param("speed", 0.5, by=MAIN)  # the main screen's commands don't count for A
    rig.at(55)
    assert rig.state.queue.controller is None


def test_the_hardware_status():
    rig = Rig()
    rig.state.set_hardware({"state": "connected", "simulated": True, "fps": 30.0, "error": None})
    assert rig.state.to_dict()["hardware"]["state"] == "connected" and rig.changes == 1
    rig.state.set_hardware({"state": "connected", "simulated": True, "fps": 30.0, "error": None})
    assert rig.changes == 1
