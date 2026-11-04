"""The real serial code path without a board (docs/plans/hcl.md, step 6).

- PtyBoard: the simulated board on the far end of a pseudo-terminal. The link
  opens the other end through pyserial exactly like /dev/ttyUSB0.
- TcpBoard: the simulated board behind a TCP server, like the Windows bridge
  (docs/hcl.md 8). The link connects with a socket:// URL.
"""

import os
import select
import socket
import threading
import time
import tty

import pytest
import serial

from hcl import Connected, Disconnected, Frame, LinkState, open_link
from hcl.transport import TransportError
from hcl.transport.serial import SerialTransport
from hcl.transport.sim import SimTransport
from support import FAST, next_of, run, until

STRIP = bytes(range(30))
MATRIX = bytes(8)


def frame(n):
    return Frame(strip=bytes([n]) + STRIP[1:], matrix=MATRIX, brightness=3)


class PtyBoard:
    """A simulated board behind a pseudo-terminal, reachable at `path`.

    `path` is a symlink to the terminal, so unplug() + plug() can put a new
    terminal behind the same name, like replugging a USB adapter."""

    def __init__(self, tmp_path, url="sim"):
        self.path = str(tmp_path / "ttyFAKE0")
        self.sim = SimTransport.from_url(url)
        self._thread = None
        self.plug()

    def plug(self):
        self.master, self._slave = os.openpty()
        tty.setraw(self._slave)  # no echo, no line editing: bytes pass through unchanged
        tmp = self.path + ".new"
        os.symlink(os.ttyname(self._slave), tmp)
        os.replace(tmp, self.path)
        self.sim.open()  # the board powers on
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._pump, name="pty-board", daemon=True)
        self._thread.start()

    def unplug(self):
        self._stop.set()
        self._thread.join(2)
        os.close(self.master)
        os.close(self._slave)
        self.sim.close()
        os.remove(self.path)

    def _pump(self):
        while not self._stop.is_set():
            ready, _, _ = select.select([self.master], [], [], 0.005)
            try:
                if ready:
                    self.sim.write(os.read(self.master, 4096))
                out = self.sim.read(4096, 0)
                if out:
                    os.write(self.master, out)
            except (OSError, TransportError):
                return


class TcpBoard:
    """A simulated board behind a TCP server: the Windows bridge's job.

    Like the bridge, the board's port stays open when the client goes away,
    so the board does not reboot between clients."""

    def __init__(self, url="sim"):
        self.sim = SimTransport.from_url(url)
        self.sim.open()
        self.server = socket.create_server(("127.0.0.1", 0))
        self.server.settimeout(0.02)
        self.url = f"socket://127.0.0.1:{self.server.getsockname()[1]}"
        self.clients = 0
        self._kick = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="tcp-board", daemon=True)
        self._thread.start()

    def kick(self):
        """Drop the current client, as if the bridge lost it."""
        self._kick.set()

    def close(self):
        self._stop.set()
        self._thread.join(2)
        self.server.close()
        self.sim.close()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.server.accept()
            except TimeoutError:
                continue
            self.clients += 1
            self._kick.clear()
            with conn:
                conn.setblocking(False)
                while not (self._stop.is_set() or self._kick.is_set()):
                    ready, _, _ = select.select([conn], [], [], 0.005)
                    try:
                        if ready:
                            data = conn.recv(4096)
                            if not data:
                                break  # the client left
                            self.sim.write(data)
                        out = self.sim.read(4096, 0)
                        if out:
                            conn.sendall(out)
                    except OSError:
                        break


@pytest.fixture
def pty_board(tmp_path):
    board = PtyBoard(tmp_path)
    yield board
    if board._thread.is_alive():
        board.unplug()


@pytest.fixture
def tcp_board():
    board = TcpBoard()
    yield board
    board.close()


# --- through a pseudo-terminal, like /dev/ttyUSB0 ----------------------------


def test_link_over_a_serial_port(pty_board):
    @run
    async def body():
        link = open_link(pty_board.path, **FAST)
        events = link.events()
        await link.start()
        try:
            event = await next_of(events, Connected)
            assert event.device.simulated is False  # seen through a real port, the link can't tell
            assert event.device.led_count == 10
            link.submit(frame(77))
            await until(lambda: pty_board.sim.board.strip_rgb() == frame(77).strip, what="the frame on the board")
            await until(lambda: link.status.frames_acked >= 1, what="an ACK")
        finally:
            await link.stop()
    body()


def test_unplug_and_replug(pty_board):
    @run
    async def body():
        link = open_link(pty_board.path, **FAST)
        events = link.events()
        await link.start()
        try:
            await next_of(events, Connected)
            link.submit(frame(5))
            await until(lambda: pty_board.sim.board.picture is not None, what="the frame")
            pty_board.unplug()
            lost = await next_of(events, Disconnected)
            assert not lost.reason.startswith("internal error")  # a port error, handled as one
            assert link.status.state is not LinkState.CONNECTED
            await until(lambda: "can't open the port" in (link.status.last_error or ""),
                        what="failed attempts while unplugged")
            pty_board.plug()  # a new terminal behind the same name, the board boots
            await next_of(events, Connected)
            await until(lambda: pty_board.sim.board.strip_rgb() == frame(5).strip, what="the frame after replugging")
            assert link.status.reconnects >= 1
        finally:
            await link.stop()
    body()


# --- through TCP, like the Windows bridge ------------------------------------


def test_link_over_tcp(tcp_board):
    @run
    async def body():
        link = open_link(tcp_board.url, **FAST)
        events = link.events()
        await link.start()
        try:
            await next_of(events, Connected)
            link.submit(frame(9))
            await until(lambda: tcp_board.sim.board.strip_rgb() == frame(9).strip, what="the frame on the board")
        finally:
            await link.stop()
    body()


def test_bridge_drops_the_client(tcp_board):
    @run
    async def body():
        link = open_link(tcp_board.url, **FAST)
        events = link.events()
        await link.start()
        try:
            await next_of(events, Connected)
            link.submit(frame(11))
            await until(lambda: tcp_board.sim.board.frames_received >= 1, what="the first frame")
            tcp_board.kick()
            lost = await next_of(events, Disconnected)
            assert not lost.reason.startswith("internal error")  # a port error, handled as one
            await next_of(events, Connected)  # the board didn't reboot: this HELLO answers a PING
            received = tcp_board.sim.board.frames_received
            await until(lambda: tcp_board.sim.board.frames_received > received, what="frames after reconnecting")
            assert tcp_board.sim.board.boots == 1
            assert tcp_board.clients == 2
        finally:
            await link.stop()
    body()


# --- the transport on its own -------------------------------------------------


def test_missing_port():
    t = SerialTransport("/dev/ttyDOESNOTEXIST")
    with pytest.raises(TransportError):
        t.open()
    with pytest.raises(TransportError, match="closed"):
        t.read(10, 0.01)
    t.close()


def test_dtr_and_rts_are_off_before_opening(monkeypatch):
    calls = []

    class FakePort:
        in_waiting = 0

        def __setattr__(self, name, value):
            calls.append((name, value))

        def open(self):
            calls.append(("open", None))

        def reset_input_buffer(self):
            calls.append(("flush", None))

        def close(self):
            pass

    def fake_serial_for_url(url, **kwargs):
        calls.append(("url", url, kwargs["do_not_open"], kwargs["baudrate"]))
        return FakePort()

    monkeypatch.setattr(serial, "serial_for_url", fake_serial_for_url)
    SerialTransport("/dev/ttyUSB0", baud=115200).open()
    assert calls == [("url", "/dev/ttyUSB0", True, 115200), ("dtr", False), ("rts", False),
                     ("open", None), ("flush", None)]


def test_read_times_out_and_returns_what_arrived(pty_board):
    # wait until the board's boot output is waiting on the line, then open: the flush drops it
    deadline = time.monotonic() + 2
    while pty_board.sim._out:
        assert time.monotonic() < deadline, "the board's boot output never went out"
        time.sleep(0.005)
    time.sleep(0.02)
    t = SerialTransport(pty_board.path)
    t.open()
    try:
        assert t.read(4096, 0.05) == b""  # the boot output from before opening was flushed
        from hcl import protocol as p
        t.write(p.encode(p.PING))
        data = b""
        for _ in range(100):
            data += t.read(4096, 0.02)
            if p.Parser().feed(data):
                break
        assert [m for m, _ in p.Parser().feed(data)] == [p.HELLO]
    finally:
        t.close()


# --- open_link ----------------------------------------------------------------


def test_open_link_picks_the_transport():
    sim = open_link("sim?latency_ms=2")
    assert isinstance(sim._t, SimTransport) and sim._t.options.latency_ms == 2
    real = open_link("/dev/ttyUSB0", baud=230400)
    assert isinstance(real._t, SerialTransport) and real._t.baud == 230400
    tcp = open_link("socket://host.docker.internal:7777")
    assert isinstance(tcp._t, SerialTransport)
    assert real.status.url == "/dev/ttyUSB0" and real.status.state is LinkState.DISCONNECTED


def test_open_link_passes_options():
    link = open_link("sim", ack_timeout_ms=33, max_fps=25)
    assert link._o.ack_timeout_ms == 33 and link._o.max_fps == 25


@pytest.mark.parametrize(
    "url, options, error",
    [
        ("sim", {"ack_timeout": 5}, "unknown link option"),
        ("sim?bogus=1", {}, "unknown sim option"),
        ("", {}, "no board URL"),
        ("sim", {"max_fps": 0}, "positive"),
    ],
)
def test_open_link_rejects(url, options, error):
    with pytest.raises(ValueError, match=error):
        open_link(url, **options)


def test_open_link_is_public():
    import hcl
    assert hcl.open_link is open_link
    assert "open_link" in hcl.__all__
