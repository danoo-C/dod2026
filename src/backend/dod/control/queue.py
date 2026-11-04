"""Turns: who controls the stand, for how long (docs/backend.md 8, tech-spec 4.6).

Pure logic: no I/O, no asyncio, the clock is passed in as `now` (monotonic
seconds), so every rule can be tested with a fake clock. Sessions are public
ids (dod.control.sessions), never tokens. Every call that changes something
returns the events it caused.

The rules:

- one controller at a time; a turn is `turn_seconds`, or until the song they
  started ends – whichever comes first. Then the turn is *over*, and it ends
  as soon as someone is waiting; with nobody waiting it simply goes on.
- an inactive controller always loses control, even when nobody waits:
  connected but no command for `inactive_seconds`, or offline that long.
  While a song they started plays, they count as active (they are watching
  it, maybe with the phone locked); the clock starts again when it ends.
- a song only ends the turn of the controller who started it; a song left
  over from the previous turn doesn't end the next one
- after a turn, joining again means the back of the line
- a waiting visitor who is offline for `inactive_seconds` leaves the queue
  (a reload is much shorter), so nobody waits for a phone that is gone
- paused (admin): turns don't end by time or song, and no new turn starts;
  inactivity, leaving and skip still end one. Resuming adds the paused time
  to the current turn.

The WebSocket layer calls connected() on a session's first connection and
disconnected() when its last one closes.
"""

from __future__ import annotations

from dataclasses import dataclass

from dod.bus import Event, QueueJoined, QueueLeft, TurnEnded, TurnStarted


@dataclass
class _Turn:
    session: str
    started: float
    ends: float
    last_activity: float
    song_playing: bool = False  # a song this controller started is playing
    over: str | None = None  # "time" or "song": ends as soon as someone waits


class Queue:
    def __init__(self, turn_seconds: float, inactive_seconds: float) -> None:
        if not turn_seconds > 0 or not inactive_seconds > 0:
            raise ValueError("turn_seconds and inactive_seconds must be positive")
        self.turn_seconds = turn_seconds
        self.inactive_seconds = inactive_seconds
        self._waiting: list[str] = []
        self._turn: _Turn | None = None
        self._offline_since: dict[str, float] = {}
        self._song_owner: str | None = None  # who started the song that is playing
        self._paused_at: float | None = None

    # --- what pages see

    @property
    def controller(self) -> str | None:
        return self._turn.session if self._turn else None

    @property
    def waiting(self) -> tuple[str, ...]:
        return tuple(self._waiting)

    @property
    def turn_ends_at(self) -> float | None:
        return self._turn.ends if self._turn else None

    @property
    def turn_over(self) -> bool:
        """The turn's time is up (or its song ended), and it goes on only because nobody waits."""
        return self._turn is not None and self._turn.over is not None

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def position(self, session: str) -> int | None:
        """0 = in control, 1 = next, ...; None = not in the queue."""
        if self.controller == session:
            return 0
        if session in self._waiting:
            return self._waiting.index(session) + 1
        return None

    # --- visitors

    def join(self, session: str, now: float) -> list[Event]:
        if self.position(session) is not None:
            return []
        self._waiting.append(session)
        return [QueueJoined(session=session, position=len(self._waiting))] + self.tick(now)

    def leave(self, session: str, now: float) -> list[Event]:
        if self.controller == session:
            return self._end("left") + self.tick(now)
        if session in self._waiting:
            self._waiting.remove(session)
            return [QueueLeft(session=session)]
        return []

    def activity(self, session: str, now: float) -> None:
        """Any command from this session."""
        if self._turn and self._turn.session == session:
            self._turn.last_activity = now

    def connected(self, session: str, now: float) -> None:
        self._offline_since.pop(session, None)

    def disconnected(self, session: str, now: float) -> None:
        self._offline_since.setdefault(session, now)

    # --- songs

    def song_started(self, session: str, now: float) -> None:
        """A song started by `session` (a visitor, or the main screen)."""
        self._song_owner = session
        if self._turn:
            mine = self._turn.session == session
            self._turn.song_playing = mine
            if mine:
                self._turn.last_activity = now

    def song_ended(self, now: float) -> list[Event]:
        """The song ended by itself: the turn of whoever started it is over."""
        owner, self._song_owner = self._song_owner, None
        t = self._turn
        if t and t.session == owner and t.song_playing:
            t.song_playing = False
            t.last_activity = now
            if t.over is None:
                t.over = "song"
        elif t:
            t.song_playing = False
        return self.tick(now)

    def song_stopped(self, now: float) -> None:
        """The song was stopped (a preset or another song was picked): no turn is over because of it."""
        self._song_owner = None
        if self._turn and self._turn.song_playing:
            self._turn.song_playing = False
            self._turn.last_activity = now

    # --- the main screen (admin)

    def skip(self, now: float) -> list[Event]:
        if self._turn is None:
            return []
        return self._end("skipped") + self.tick(now)

    def pause(self, now: float) -> None:
        if self._paused_at is None:
            self._paused_at = now

    def resume(self, now: float) -> list[Event]:
        if self._paused_at is None:
            return []
        if self._turn:
            self._turn.ends += now - self._paused_at
        self._paused_at = None
        return self.tick(now)

    # --- the clock

    def tick(self, now: float) -> list[Event]:
        """Called a few times a second, and after every change."""
        events: list[Event] = []
        for session in list(self._waiting):
            since = self._offline_since.get(session)
            if since is not None and now - since >= self.inactive_seconds:
                self._waiting.remove(session)
                events.append(QueueLeft(session=session, reason="gone"))
        t = self._turn
        if t is not None:
            if not self.paused and t.over is None and now >= t.ends:
                t.over = "time"
            if self._inactive(t, now):
                events += self._end("inactive")
            elif t.over is not None and self._waiting and not self.paused:
                events += self._end(t.over)
        if self._turn is None and self._waiting and not self.paused:
            session = self._waiting.pop(0)
            self._turn = _Turn(session=session, started=now, ends=now + self.turn_seconds, last_activity=now)
            events.append(TurnStarted(session=session, waiting=len(self._waiting)))
        # only sessions in the queue need their offline time; the rest would pile up all day
        for session in [s for s in self._offline_since if self.position(s) is None]:
            del self._offline_since[session]
        return events

    def _inactive(self, t: _Turn, now: float) -> bool:
        if t.song_playing:
            return False
        quiet_since = t.last_activity
        offline = self._offline_since.get(t.session)
        if offline is not None:
            quiet_since = max(quiet_since, offline)
        return now - quiet_since >= self.inactive_seconds

    def _end(self, reason: str) -> list[Event]:
        assert self._turn is not None
        session, self._turn = self._turn.session, None
        return [TurnEnded(session=session, reason=reason)]
