"""The player's rules (backend.md 6; plan step 8). The main screen plays the
song; this decides when a song starts and when it is over, and the state
keeps the mode and the queue right (State.song_started / song_ended).

- play_song is refused with `no_player` while no main screen is connected,
  and with `unknown_song` for a song that isn't on the list or downloaded
- a song ends at the first of:
  1. the main screen says `player` with `ended: true`            -> "ended"
  2. `started + length + GRACE` – the length is known from the download -> "overran"
  3. no `player` message for PLAYER_TIMEOUT while it plays        -> "player_gone"
  (the main screen was closed or reloaded, or the browser blocked the sound)
- a song keeps playing when the turn ends; the next controller stops it by
  picking a preset or another song (the state does that)

tick() is called by the queue clock, a few times a second.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from dod.api import messages as m
from dod.music.library import Library
from dod.state import State

GRACE = 10.0  # seconds after the song's length before it counts as over
PLAYER_TIMEOUT = 10.0  # seconds without a `player` message


class Player:
    def __init__(self, state: State, library: Library, clock: Callable[[], float] = time.monotonic) -> None:
        # the state's clock: song.started is on it
        self._state = state
        self._library = library
        self._clock = clock
        self._heard = 0.0  # the last `player` message for the current song (or its start)

    def play(self, song: str, who: str) -> m.ErrorCode | None:
        """The hub's play_song: an error code, or None if it plays."""
        if not self._state.player_connected:
            return "no_player"
        entry = self._library.song(song)
        length = self._library.length(song)
        if entry is None or length is None:
            return "unknown_song"
        self._heard = self._clock()
        self._state.song_started(song, entry.title, length, by=who)
        return None

    def on_player(self, msg: m.Player) -> None:
        """The hub's on_player: the main screen says how far the song is."""
        current = self._state.song
        if current is None or msg.song != current.song:
            return  # an old song's last messages
        self._heard = self._clock()
        if msg.ended:
            self._state.song_ended("ended")

    def tick(self) -> None:
        current = self._state.song
        if current is None:
            return
        now = self._clock()
        if now > current.started + current.length + GRACE:
            self._state.song_ended("overran")
        elif now - max(self._heard, current.started) > PLAYER_TIMEOUT:
            self._state.song_ended("player_gone")
