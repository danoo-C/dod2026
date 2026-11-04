"""The player's rules (backend.md 6; plan step 8), with a fake clock."""

import json

import pytest

from dod.api.messages import Player as PlayerMessage
from dod.bus import Bus, SongEnded, SongStarted, TurnEnded
from dod.music.library import Library, Song
from dod.music.player import GRACE, PLAYER_TIMEOUT, Player
from dod.settings import Settings
from dod.state import State

SONG = "dQw4w9WgXcQ"
OTHER = "y6120QOlsfU"
A, B = "aaaa11112222", "bbbb33334444"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def stand(tmp_path):
    for song_id, length in ((SONG, 213.0), (OTHER, 225.0)):
        (tmp_path / f"{song_id}.mp4").write_bytes(b"x")
        (tmp_path / f"{song_id}.json").write_text(json.dumps({"length": length}))
    clock, bus = Clock(), Bus()
    events = bus.subscribe()
    state = State(Settings(internal_key="k"), bus, clock=clock)
    library = Library([Song(SONG, "Never Gonna"), Song(OTHER, "Sandstorm"), Song("9bZkp7q19f0", "Gangnam")], tmp_path)
    player = Player(state, library, clock=clock)
    state.set_player_connected(True)
    for who in (A, B):
        state.connected(who)
        state.join(who)  # A controls, B waits
    state.set_preset("fire", by=A)
    return state, player, clock, events


def heard(player, song=SONG, position=1.0, ended=False):
    player.on_player(PlayerMessage(type="player", song=song, position=position, ended=ended))


def test_a_song_plays(stand):
    state, player, clock, events = stand
    assert player.play(SONG, A) is None
    assert state.mode == "music" and state.song.song == SONG and state.song.length == 213.0
    assert any(isinstance(e, SongStarted) and e.title == "Never Gonna" for e in events.take_all())


def test_no_main_screen_no_player(stand):
    state, player, _, _ = stand
    state.set_player_connected(False)
    assert player.play(SONG, A) == "no_player"
    assert state.mode == "manual"


@pytest.mark.parametrize("song", ["9bZkp7q19f0", "zzzzzzzzzzz"])  # listed but not downloaded; not on the list
def test_unknown_songs(stand, song):
    state, player, _, _ = stand
    assert player.play(song, A) == "unknown_song"
    assert state.mode == "manual"


def test_ending_1_the_main_screen_says_it_ended(stand):
    state, player, clock, _ = stand
    player.play(SONG, A)
    clock.t += 213
    heard(player, ended=True)
    assert state.mode == "manual" and state.preset == "fire" and state.song is None


def test_ending_2_it_overran_its_length(stand):
    state, player, clock, _ = stand
    player.play(SONG, A)
    for _ in range(int(213 + GRACE)):  # the main screen keeps saying it plays, but never that it ended
        clock.t += 1
        heard(player, position=min(213, clock.t - 1000))
        player.tick()
    assert state.mode == "music"
    clock.t += 1
    heard(player)
    player.tick()
    assert state.mode == "manual" and state.preset == "fire"


def test_ending_3_the_main_screen_went_quiet(stand):
    state, player, clock, events = stand
    player.play(SONG, A)
    clock.t += PLAYER_TIMEOUT - 1
    player.tick()
    assert state.mode == "music"
    clock.t += 2
    player.tick()
    assert state.mode == "manual" and state.preset == "fire"
    assert any(isinstance(e, SongEnded) and e.reason == "player_gone" for e in events.take_all())


def test_player_messages_keep_it_alive(stand):
    state, player, clock, _ = stand
    player.play(SONG, A)
    for _ in range(30):  # 30 s of messages once a second
        clock.t += 1
        heard(player)
        player.tick()
    assert state.mode == "music"


def test_messages_for_an_old_song_are_ignored(stand):
    state, player, clock, _ = stand
    player.play(OTHER, A)
    player.play(SONG, A)  # replaces it
    heard(player, song=OTHER, ended=True)  # the old one's last message
    assert state.song.song == SONG
    clock.t += PLAYER_TIMEOUT + 1
    heard(player, song=OTHER)  # doesn't count as hearing the new one
    player.tick()
    assert state.song is None


def test_the_controllers_own_song_ending_ends_the_turn_when_someone_waits(stand):
    state, player, clock, events = stand
    player.play(SONG, A)
    clock.t += 213
    heard(player, ended=True)
    state.tick()
    assert state.queue.controller == B
    assert any(isinstance(e, TurnEnded) and e.session == A and e.reason == "song" for e in events.take_all())


def test_a_stopped_song_doesnt_end_the_turn(stand):
    state, player, _, _ = stand
    player.play(SONG, A)
    state.set_preset("rainbow", by=A)  # the controller picked a preset instead
    state.tick()
    assert state.queue.controller == A and state.mode == "manual"
