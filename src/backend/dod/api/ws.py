"""The WebSocket hub (docs/backend.md 9): one connection per browser,
`/ws?role=phone|main|logging`.

On connect: the session cookie (4401 without it), the internal key for
`main` and `logging` (4403 without it), then `welcome`, `state` and `you`.
After that: commands in, checked for who may send them; `state` (at most
20 a second, coalesced), `you` (when it changes for that browser),
`preview` (10 a second) and `log` (main and logging only) out.

Every connection has its own outgoing queue and writer task, so a slow phone
never holds up the others: when its queue is full, its oldest message is
dropped (state and you are full snapshots, so the newest one is enough).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from fastapi import APIRouter, WebSocket
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from dod.api import messages as m
from dod.bus import Bus, LoadingStarted
from dod.control.sessions import INTERNAL_COOKIE, MAIN, key_matches, public_id, session_token, short
from dod.engine.effects import PRESETS
from dod.engine.output import PreviewFrame
from dod.settings import Settings
from dod.state import State

log = logging.getLogger(__name__)

router = APIRouter()

MAX_MESSAGE = 65536  # bytes; uvicorn's --ws-max-size says the same, this also holds without it
STATE_INTERVAL = 0.05  # at most 20 state messages a second
OUT_QUEUE = 64  # messages waiting for one browser before the oldest is dropped
PHONE_RATE = 20.0  # commands a second from one phone (a slider being dragged)
PHONE_BURST = 20
LOG_ROLES = ("main", "logging")  # phones never get the log stream: it would use up the hotspot

CLOSE_REPLACED = 4001  # a newer main screen took over
CLOSE_BAD_ROLE = 4400
CLOSE_NO_SESSION = 4401
CLOSE_NO_KEY = 4403
CLOSE_TOO_BIG = 1009
CLOSE_GOING_AWAY = 1001  # the backend shuts down

# what the player (plan step 8) plugs in; until then: nobody can play
PlaySong = Callable[[str, str], m.ErrorCode | None]  # (song, who) -> an error code, or None if it plays
OnSpectrum = Callable[[m.Spectrum], None]
OnPlayer = Callable[[m.Player], None]


@router.websocket("/ws")
async def websocket(ws: WebSocket) -> None:
    await ws.app.state.hub.serve(ws)


class RateLimit:
    """A token bucket: `rate` a second on average, up to `burst` at once."""

    def __init__(self, rate: float = PHONE_RATE, burst: int = PHONE_BURST,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.rate, self.burst, self._clock = rate, burst, clock
        self._tokens = float(burst)
        self._at = clock()

    def allow(self) -> bool:
        now = self._clock()
        self._tokens = min(self.burst, self._tokens + (now - self._at) * self.rate)
        self._at = now
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False


@dataclass(eq=False)
class Connection:
    ws: WebSocket
    role: str
    session: str  # public id from the cookie
    out: asyncio.Queue[str | int] = field(default_factory=lambda: asyncio.Queue(OUT_QUEUE))
    rate: RateLimit = field(default_factory=RateLimit)
    limited: bool = False  # is being rate limited (told once)
    last_you: str | None = None
    closing: bool = False

    @property
    def who(self) -> str:
        """Who commands come from: the main screen is MAIN, everyone else their public id."""
        return MAIN if self.role == "main" else self.session

    def send(self, text: str) -> None:
        if self.closing:
            return
        if self.out.full():
            self.out.get_nowait()  # a slow browser loses its oldest message
        self.out.put_nowait(text)

    def close(self, code: int) -> None:
        """Close from any task: the writer sends the close, after what is queued."""
        if self.closing:
            return
        if self.out.full():
            self.out.get_nowait()
        self.out.put_nowait(code)
        self.closing = True

    async def writer(self) -> None:
        """The only task that writes to this WebSocket."""
        try:
            while True:
                item = await self.out.get()
                if isinstance(item, int):
                    await self.ws.close(item)
                    return
                await self.ws.send_text(item)
        except Exception:  # the browser is gone; the reader notices too
            return


class Hub:
    def __init__(self, state: State, bus: Bus, settings: Settings, *,
                 songs: Callable[[], Iterable[m.SongInfo]] = lambda: [],
                 play_song: PlaySong | None = None,
                 on_spectrum: OnSpectrum | None = None,
                 on_player: OnPlayer | None = None,
                 log_history: Callable[[], list[m.LogLine]] | None = None) -> None:
        self._state = state
        self._log_history = log_history  # the last lines, for a main or logging page that connects
        self._bus = bus
        self._settings = settings
        self._songs = songs
        self._play_song = play_song or self._no_songs_yet
        self._on_spectrum = on_spectrum
        self._on_player = on_player
        self.connections: set[Connection] = set()
        self._main: Connection | None = None
        self._phones: Counter[str] = Counter()  # open phone connections per session
        self._dirty = asyncio.Event()
        self.closed = False

    # --- the state's listener, and the broadcaster task

    def state_changed(self, state: State) -> None:
        self._dirty.set()

    async def run(self) -> None:
        """Task: send the state when it changed, at most every STATE_INTERVAL."""
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            self._broadcast_state()
            await asyncio.sleep(STATE_INTERVAL)

    def _broadcast_state(self) -> None:
        text = self._state_text()
        for conn in list(self.connections):
            conn.send(text)
            self._send_you(conn)

    def _state_text(self) -> str:
        return m.StateMessage.model_validate({"type": "state", **self._state.to_dict()}).model_dump_json()

    def _send_you(self, conn: Connection) -> None:
        text = m.You.model_validate({"type": "you", **self._state.you(conn.session)}).model_dump_json()
        if text != conn.last_you:
            conn.last_you = text
            conn.send(text)

    # --- previews and logs

    def preview(self, frame: PreviewFrame) -> None:
        """The render loop's on_preview: one message, the same text to every browser."""
        if not self.connections:
            return
        text = m.Preview(leds=frame.hex_leds(), matrix=frame.matrix.hex(),
                         brightness=frame.matrix_brightness).model_dump_json()
        for conn in list(self.connections):
            conn.send(text)

    def send_log(self, lines: list[m.LogLine]) -> None:
        """A batch of log lines to the main screen and the logging pages; phones never get them."""
        text = m.Log(lines=lines).model_dump_json()
        for conn in list(self.connections):
            if conn.role in LOG_ROLES:
                conn.send(text)

    def _send_log_history(self, conn: Connection) -> None:
        if conn.role not in LOG_ROLES or self._log_history is None:
            return
        lines = self._log_history()
        if lines:
            conn.send(m.Log(lines=lines).model_dump_json())

    # --- one browser

    async def serve(self, ws: WebSocket) -> None:
        await ws.accept()  # accepted first, so the browser sees the close code
        role = ws.query_params.get("role")
        if self.closed:
            await ws.close(CLOSE_GOING_AWAY)
            return
        if role not in m.ROLES:
            await ws.close(CLOSE_BAD_ROLE)
            return
        token = session_token(ws.cookies)
        if token is None:
            await ws.close(CLOSE_NO_SESSION)
            return
        if role != "phone" and not key_matches(ws.cookies.get(INTERNAL_COOKIE), self._settings.internal_key):
            await ws.close(CLOSE_NO_KEY)
            return

        conn = Connection(ws=ws, role=role, session=public_id(token))
        self._register(conn)
        writer = asyncio.create_task(conn.writer())
        try:
            conn.send(self._welcome(conn))
            conn.send(self._state_text())
            self._send_you(conn)
            self._send_log_history(conn)  # before any new line: nothing awaited since _register
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                text = message.get("text")
                if text is None:
                    data = message.get("bytes") or b""
                    if len(data) > MAX_MESSAGE:
                        conn.close(CLOSE_TOO_BIG)
                        break
                    self._error(conn, "invalid", "messages are JSON text")
                    continue
                if len(text.encode("utf-8")) > MAX_MESSAGE:
                    conn.close(CLOSE_TOO_BIG)
                    break
                self._handle(conn, text)
        except WebSocketDisconnect:
            pass
        finally:
            self._unregister(conn)
            if conn.closing:
                await asyncio.wait([writer], timeout=1)  # let it send the close
            writer.cancel()

    def _register(self, conn: Connection) -> None:
        self.connections.add(conn)
        if conn.role == "main":
            old, self._main = self._main, conn
            if old is not None:
                log.info("a newer main screen replaced the old one")
                old.close(CLOSE_REPLACED)
            self._state.set_player_connected(True)
        elif conn.role == "phone":
            self._phones[conn.session] += 1
            if self._phones[conn.session] == 1:
                self._state.connected(conn.session)

    def _unregister(self, conn: Connection) -> None:
        self.connections.discard(conn)
        if conn.role == "main":
            if self._main is conn:
                self._main = None
                self._state.set_player_connected(False)
        elif conn.role == "phone":
            self._phones[conn.session] -= 1
            if self._phones[conn.session] <= 0:
                del self._phones[conn.session]
                self._state.disconnected(conn.session)

    def _welcome(self, conn: Connection) -> str:
        s = self._settings
        return m.Welcome(
            role=conn.role,  # type: ignore[arg-type]
            session=short(conn.session),
            presets=[m.PresetInfo.model_validate(e.describe()) for e in PRESETS.values()],
            songs=list(self._songs()),
            public_url=s.public_url,
            turn_seconds=s.turn_seconds,
            inactive_seconds=s.inactive_seconds,
            # the main screen shows it as a QR code; nobody else needs it
            wifi=(m.WifiInfo(ssid=s.wifi_ssid, password=s.wifi_password)
                  if conn.role == "main" and s.wifi_ssid is not None and s.wifi_password is not None else None),
        ).model_dump_json()

    # --- commands

    def _error(self, conn: Connection, code: m.ErrorCode, message: str) -> None:
        conn.send(m.Error(code=code, message=message).model_dump_json())

    def _handle(self, conn: Connection, text: str) -> None:
        if conn.role == "phone":
            if not conn.rate.allow():
                if not conn.limited:
                    conn.limited = True
                    self._error(conn, "rate_limited", "too many commands; some were dropped")
                return
            conn.limited = False
        try:
            msg = m.parse(text)
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(p) for p in first["loc"]) or "message"
            self._error(conn, "invalid", f"{where}: {first['msg']}")
            return
        try:
            self._dispatch(conn, msg)
        except ValueError as e:  # the state refused a value
            self._error(conn, "invalid", str(e))

    def _dispatch(self, conn: Connection, msg: m.Incoming) -> None:
        state, who = self._state, conn.who
        match msg:
            case m.JoinQueue() | m.LeaveQueue():
                if conn.role != "phone":
                    return self._error(conn, "forbidden", "only phones queue up")
                (state.join if isinstance(msg, m.JoinQueue) else state.leave)(who)
            case m.SetPreset() | m.SetParam() | m.SetMatrix() | m.PlaySong():
                if conn.role == "logging":
                    return self._error(conn, "forbidden", "the logging page only watches")
                if not state.may_control(who):
                    return self._error(conn, "not_your_turn", "wait for your turn")
                match msg:
                    case m.SetPreset(preset=preset):
                        state.set_preset(preset, by=who)
                    case m.SetParam(name=name, value=value):
                        state.set_param(name, value, by=who)
                    case m.SetMatrix(mode=mode, drawing=drawing):
                        state.set_matrix(mode, drawing, by=who)
                    case m.PlaySong(song=song):
                        error = self._play_song(song, who)
                        if error is not None:
                            self._error(conn, error, f"can't play {song}")
            case m.LoadingStarted():
                self._bus.publish(LoadingStarted(by=short(who)))
            case m.Spectrum() | m.Player() | m.Admin():
                if conn.role != "main":
                    return self._error(conn, "forbidden", "only the main screen may send this")
                match msg:
                    case m.Spectrum():
                        if self._on_spectrum is not None:
                            self._on_spectrum(msg)
                    case m.Player():
                        if self._on_player is not None:
                            self._on_player(msg)
                    case m.Admin(action="skip"):
                        state.skip()
                    case m.Admin(action="pause_queue"):
                        state.pause_queue()
                    case m.Admin(action="resume_queue"):
                        state.resume_queue()
                    case m.Admin(action="stop_song"):
                        state.song_ended("stopped")

    def _no_songs_yet(self, song: str, who: str) -> m.ErrorCode | None:
        if not self._state.player_connected:
            return "no_player"
        return "unknown_song"

    # --- shutdown

    def close_all(self) -> None:
        """Stop taking connections and close the open ones."""
        self.closed = True
        for conn in list(self.connections):
            conn.close(CLOSE_GOING_AWAY)
