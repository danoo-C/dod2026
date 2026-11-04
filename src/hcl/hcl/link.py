"""The link: gets frames onto the board and keeps the connection alive (docs/hcl.md 4).

One I/O thread owns the transport: it opens it, reads and parses what the
board sends, and writes frames. The backend's asyncio side only touches the
frame slot (submit), reads status snapshots, and receives events, so the
event loop never waits for the port.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

from hcl import protocol
from hcl.color import reorder
from hcl.rawtext import LineCollector
from hcl.transport.base import Transport, TransportError
from hcl.types import (
    Connected,
    DeviceInfo,
    DeviceLog,
    Disconnected,
    Frame,
    Incompatible,
    LinkEvent,
    LinkState,
    LinkStatus,
    LogLevel,
    RawText,
)

log = logging.getLogger("hcl")

STATS_WINDOW = 2.0  # seconds that fps and rtt_ms are averaged over
READ_CHUNK = 4096
POLL = 0.005  # longest a single read waits, so a submitted frame goes out within ~5 ms
RAW_TEXT_FLUSH = 0.2  # an unfinished text line is shown after this much quiet
JOIN_TIMEOUT = 2.0


@dataclass(frozen=True)
class LinkOptions:
    """Timings of the link (docs/hcl.md 3.1). The defaults are for the real board."""

    ack_timeout_ms: float = 100  # give up waiting for an ACK
    hello_timeout_ms: float = 5000  # wait for HELLO after opening the port
    keepalive_ms: float = 1000  # resend the last frame if nothing new came
    max_fps: float = 60  # never send faster than this
    ping_interval_ms: float = 500  # PING while waiting for HELLO
    incompatible_ping_ms: float = 5000  # PING an incompatible board, in case it gets new code
    max_ack_timeouts: int = 3  # this many in a row = the board is gone
    partial_timeout_ms: float = 50  # drop a message that doesn't complete
    backoff_ms: tuple[float, ...] = (500, 1000, 2000, 5000)  # waits between reconnect attempts
    event_queue: int = 1000  # events kept per listener that doesn't keep up

    def __post_init__(self) -> None:
        for name in ("ack_timeout_ms", "hello_timeout_ms", "keepalive_ms", "max_fps",
                     "ping_interval_ms", "incompatible_ping_ms", "partial_timeout_ms"):
            if getattr(self, name) <= 0:
                raise ValueError(f"link option {name} must be positive")
        if self.max_ack_timeouts < 1 or self.event_queue < 1:
            raise ValueError("link options max_ack_timeouts and event_queue must be at least 1")
        if not self.backoff_ms or any(b < 0 for b in self.backoff_ms):
            raise ValueError("link option backoff_ms needs at least one wait, none negative")


class _SessionEnded(Exception):
    """The board stopped answering: close the port and start over."""


_END = object()  # tells an EventStream that the link stopped


class EventStream:
    """One listener's events (docs/hcl.md 3.5): `async for event in stream`.

    Each listener has its own queue. If a listener falls behind by more than
    `event_queue` events, its oldest ones are dropped (counted in `dropped`),
    so a slow listener never holds up the others or the link.
    The stream ends when the link stops.
    """

    def __init__(self, link: Link, size: int) -> None:
        self._link = link
        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=size)
        self.dropped = 0

    def __aiter__(self) -> EventStream:
        return self

    async def __anext__(self) -> LinkEvent:
        item = await self._queue.get()
        if item is _END:
            self.close()
            raise StopAsyncIteration
        return item  # type: ignore[return-value]

    def close(self) -> None:
        """Stop listening."""
        self._link._streams.discard(self)

    def _offer(self, item: object) -> None:
        if self._queue.full():
            self._queue.get_nowait()
            self.dropped += 1
        self._queue.put_nowait(item)


class Link:
    """The connection to one board. Create it with open_link() (docs/hcl.md 3)."""

    def __init__(self, transport: Transport, url: str = "", options: LinkOptions | None = None) -> None:
        self._t = transport
        self._url = url
        self._o = options or LinkOptions()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._stopped = False
        self._streams: set[EventStream] = set()

        # shared between the I/O thread and the caller, always under _lock
        self._lock = threading.Lock()
        self._slot: Frame | None = None
        self._state = LinkState.DISCONNECTED
        self._device: DeviceInfo | None = None
        self._connected_since: float | None = None
        self._acks: deque[tuple[float, float]] = deque()  # (time, round trip) of recent ACKs
        self._frames_sent = 0
        self._frames_acked = 0
        self._frames_replaced = 0
        self._ack_timeouts = 0
        self._reconnects = 0
        self._bytes_tx = 0
        self._bytes_rx = 0
        self._garbage_done = 0  # garbage counted by parsers of finished sessions
        self._last_error: str | None = None
        self._parser: protocol.Parser | None = None

        # only the I/O thread touches these
        self._lines = LineCollector()
        self._last_frame: Frame | None = None  # sent again by keepalive and after a reconnect
        self._resend = False
        self._seq = 0
        self._in_flight: tuple[int, float] | None = None  # (seq, sent at)
        self._last_send = float("-inf")
        self._timeouts_in_row = 0
        self._next_ping = 0.0

    # --- public API -----------------------------------------------------

    async def start(self) -> None:
        """Start connecting in the background. Returns at once; watch status or events."""
        if self._thread is not None:
            raise RuntimeError("the link was already started")
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._run, name="hcl-io", daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        """Close the port and stop the I/O thread. Event streams end. Safe to call twice."""
        if self._stopped:
            return
        self._stopped = True
        self._stop.set()
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, JOIN_TIMEOUT)
            if self._thread.is_alive():
                log.warning("hcl: the I/O thread did not stop within %.0f s", JOIN_TIMEOUT)
        # queued after every event the thread sent, so nothing arrives after the end
        loop = asyncio.get_running_loop()
        loop.call_soon(self._end_streams)
        await asyncio.sleep(0)

    def submit(self, frame: Frame) -> None:
        """Hand over the newest picture. Never blocks: if the previous one wasn't
        sent yet, it is replaced (docs/hcl.md 3.3)."""
        if not isinstance(frame, Frame):
            raise TypeError(f"submit() takes a Frame, got {type(frame).__name__}")
        if self._stopped:
            raise RuntimeError("the link is stopped")
        with self._lock:
            device = self._device
            if device is not None and frame.led_count != device.led_count:
                raise ValueError(f"frame has {frame.led_count} LEDs, the connected board has {device.led_count}")
            if self._slot is not None:
                self._frames_replaced += 1
            self._slot = frame

    @property
    def status(self) -> LinkStatus:
        """A snapshot (docs/hcl.md 3.4)."""
        now = time.monotonic()
        with self._lock:
            while self._acks and now - self._acks[0][0] > STATS_WINDOW:
                self._acks.popleft()
            rtts = [rtt for _, rtt in self._acks]
            return LinkStatus(
                state=self._state,
                url=self._url,
                device=self._device,
                connected_since=self._connected_since,
                fps=round(len(rtts) / STATS_WINDOW, 1),
                rtt_ms=round(1000 * sum(rtts) / len(rtts), 2) if rtts else None,
                rtt_min_ms=round(1000 * min(rtts), 2) if rtts else None,
                rtt_max_ms=round(1000 * max(rtts), 2) if rtts else None,
                frames_sent=self._frames_sent,
                frames_acked=self._frames_acked,
                frames_replaced=self._frames_replaced,
                ack_timeouts=self._ack_timeouts,
                garbage_bytes=self._garbage_done + (self._parser.garbage_count if self._parser else 0),
                reconnects=self._reconnects,
                bytes_tx=self._bytes_tx,
                bytes_rx=self._bytes_rx,
                last_error=self._last_error,
            )

    def events(self, queue_size: int | None = None) -> EventStream:
        """A new listener. It receives every event from now on. It keeps up to
        queue_size unread events (default: the event_queue option)."""
        size = self._o.event_queue if queue_size is None else queue_size
        if size < 1:
            raise ValueError("queue_size must be at least 1")
        stream = EventStream(self, size)
        if self._stopped:
            stream._offer(_END)
        else:
            self._streams.add(stream)
        return stream

    # --- the I/O thread -------------------------------------------------

    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                self._t.open()
            except Exception as e:  # TransportError, or a bug in a transport
                if not isinstance(e, TransportError):
                    log.exception("hcl: opening the transport failed")
                self._set_error(f"can't open the port: {e}")
                self._backoff(attempt)
                attempt += 1
                continue

            reason = "the link was stopped"
            try:
                self._session()
            except (_SessionEnded, TransportError) as e:
                reason = str(e)
            except Exception as e:
                log.exception("hcl: unexpected error in the I/O thread")
                reason = f"internal error: {e!r}"
            finally:
                try:
                    self._t.close()
                except Exception:
                    log.exception("hcl: closing the transport failed")

            with self._lock:
                was = self._state
                self._state = LinkState.DISCONNECTED
                self._device = None
                self._connected_since = None
                if self._parser is not None:
                    self._garbage_done += self._parser.garbage_count
                    self._parser = None
            if self._stop.is_set():
                break
            self._set_error(reason)
            if was in (LinkState.CONNECTED, LinkState.INCOMPATIBLE):
                self._emit(Disconnected(reason))
                attempt = 0  # it worked before: try again soon
            with self._lock:
                self._reconnects += 1
            self._backoff(attempt)
            attempt += 1

    def _session(self) -> None:
        """One open port, from PING until the board is lost or the link stops."""
        o = self._o
        with self._lock:
            self._parser = protocol.Parser()
            self._state = LinkState.CONNECTING
        parser = self._parser
        self._lines = LineCollector()
        self._in_flight = None
        self._timeouts_in_row = 0
        self._seq = 0
        now = time.monotonic()
        hello_deadline = now + o.hello_timeout_ms / 1000
        self._next_ping = now
        last_rx = now

        while not self._stop.is_set():
            now = time.monotonic()
            state = self._state
            if state is LinkState.CONNECTING:
                if now >= hello_deadline:
                    raise _SessionEnded(f"no HELLO from the board within {o.hello_timeout_ms / 1000:g} s")
                if now >= self._next_ping:
                    self._write(protocol.encode(protocol.PING))
                    self._next_ping = now + o.ping_interval_ms / 1000
            elif state is LinkState.INCOMPATIBLE:
                if now >= self._next_ping:
                    self._write(protocol.encode(protocol.PING))
                    self._next_ping = now + o.incompatible_ping_ms / 1000
            else:
                self._send_step(now)

            data = self._t.read(READ_CHUNK, POLL)
            now = time.monotonic()
            if data:
                last_rx = now
                with self._lock:
                    self._bytes_rx += len(data)
                for type_, payload in parser.feed(data):
                    self._handle(type_, payload, now)
                self._raw_text(self._lines.feed(parser.take_garbage()))
            elif parser.pending() and now - last_rx >= o.partial_timeout_ms / 1000:
                parser.reset_partial()
                self._raw_text(self._lines.feed(parser.take_garbage()))
            if now - last_rx >= RAW_TEXT_FLUSH:
                self._raw_text(self._lines.flush())

    def _handle(self, type_: int, payload: bytes, now: float) -> None:
        if type_ == protocol.HELLO:
            self._on_hello(payload, now)
        elif type_ == protocol.ACK:
            try:
                seq = protocol.parse_ack(payload)
            except ValueError:
                return
            if self._in_flight is not None and self._in_flight[0] == seq:
                rtt = now - self._in_flight[1]
                self._in_flight = None
                self._timeouts_in_row = 0
                with self._lock:
                    self._frames_acked += 1
                    self._acks.append((now, rtt))
            # an ACK for another seq is a late one: ignored
        elif type_ == protocol.LOG:
            try:
                level, text = protocol.parse_log(payload)
            except ValueError:
                return
            self._emit(DeviceLog(LogLevel.from_wire(level), text))
        # anything else is a message for the board, not for us: ignored

    def _on_hello(self, payload: bytes, now: float) -> None:
        try:
            version = protocol.hello_version(payload)
        except ValueError:
            return
        self._in_flight = None  # a HELLO means the board (re)started: no ACK is coming
        if version != protocol.PROTOCOL_VERSION:
            self._next_ping = now + self._o.incompatible_ping_ms / 1000
            if self._state is not LinkState.INCOMPATIBLE:
                reason = (f"the board speaks protocol {version}, this host speaks {protocol.PROTOCOL_VERSION}; "
                          "put the current code on the board (./dod esp upload)")
                with self._lock:
                    self._state = LinkState.INCOMPATIBLE
                    self._device = None
                    self._connected_since = None
                    self._last_error = reason
                self._emit(Incompatible(reason, protocol=version))
            return
        try:
            _, firmware, led_count, color_order = protocol.parse_hello(payload)
        except ValueError as e:
            self._set_error(f"bad HELLO from the board: {e}")
            return
        device = DeviceInfo(protocol=version, firmware=firmware, led_count=led_count,
                            color_order=color_order, simulated=self._t.simulated)
        rebooted = self._state is LinkState.CONNECTED
        self._timeouts_in_row = 0
        self._resend = self._last_frame is not None
        with self._lock:
            self._state = LinkState.CONNECTED
            self._device = device
            self._connected_since = time.time()
        self._emit(Connected(device, rebooted=rebooted))

    def _send_step(self, now: float) -> None:
        o = self._o
        if self._in_flight is not None:
            if now - self._in_flight[1] < o.ack_timeout_ms / 1000:
                return
            self._in_flight = None
            self._timeouts_in_row += 1
            with self._lock:
                self._ack_timeouts += 1
            if self._timeouts_in_row >= o.max_ack_timeouts:
                raise _SessionEnded(f"the board stopped answering ({self._timeouts_in_row} ACK timeouts in a row)")
        if now - self._last_send < 1 / o.max_fps:
            return
        with self._lock:
            frame = self._slot
            self._slot = None
            device = self._device
        if frame is None:
            if self._last_frame is None:
                return
            if not self._resend and now - self._last_send < o.keepalive_ms / 1000:
                return
            frame = self._last_frame
        self._resend = False
        assert device is not None
        if frame.led_count != device.led_count:
            # submitted before the board said how many LEDs it has
            self._set_error(f"frame has {frame.led_count} LEDs, the board has {device.led_count}; frame dropped")
            return
        self._seq = (self._seq + 1) & 0xFF
        strip = reorder(frame.strip, "RGB", device.color_order)
        self._write(protocol.encode(protocol.FRAME, protocol.frame_payload(self._seq, strip, frame.matrix, frame.brightness)))
        self._in_flight = (self._seq, now)
        self._last_send = now
        self._last_frame = frame
        with self._lock:
            self._frames_sent += 1

    def _write(self, data: bytes) -> None:
        self._t.write(data)
        with self._lock:
            self._bytes_tx += len(data)

    def _raw_text(self, lines: list[str]) -> None:
        for line in lines:
            self._emit(RawText(line))

    def _set_error(self, text: str) -> None:
        log.info("hcl: %s", text)
        with self._lock:
            self._last_error = text

    def _backoff(self, attempt: int) -> None:
        waits = self._o.backoff_ms
        self._stop.wait(waits[min(attempt, len(waits) - 1)] / 1000)

    # --- events, delivered on the event loop ----------------------------

    def _emit(self, event: LinkEvent) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._dispatch, event)
        except RuntimeError:
            pass  # the event loop is closed: nobody is listening any more

    def _dispatch(self, event: LinkEvent) -> None:
        for stream in list(self._streams):
            stream._offer(event)

    def _end_streams(self) -> None:
        for stream in list(self._streams):
            stream._offer(_END)
        self._streams.clear()
