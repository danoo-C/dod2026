import time

import pytest

from hcl import protocol as p
from hcl.color import reorder
from hcl.rawtext import LineCollector
from hcl.transport import TransportError
from hcl.transport.sim import SimOptions, SimTransport, parse_sim_url

STRIP_RGB = bytes(range(30))
MATRIX = bytes([0xFF, 0, 0x81, 0, 0x18, 0, 0x81, 0xFF])


class Reader:
    """Reads from a transport and sorts what comes out into messages and text."""

    def __init__(self, transport):
        self.t = transport
        self.parser = p.Parser()
        self.lines = LineCollector()
        self.messages = []
        self.text = []

    def pump(self, until, timeout=2.0):
        """Read until until(self) is true; fail after `timeout` seconds."""
        deadline = time.monotonic() + timeout
        while not until(self):
            if time.monotonic() > deadline:
                pytest.fail(f"timed out; messages={self.messages!r} text={self.text!r}")
            self.feed(self.t.read(4096, 0.02))
        return self

    def feed(self, data):
        self.messages += self.parser.feed(data)
        self.text += self.lines.feed(self.parser.take_garbage())

    def of(self, type_):
        return [payload for t, payload in self.messages if t == type_]


def frame(seq, strip=None):
    return p.encode(p.FRAME, p.frame_payload(seq, strip if strip is not None else reorder(STRIP_RGB, "RGB", "GRB"), MATRIX, 9))


def opened(url="sim"):
    t = SimTransport.from_url(url)
    t.open()
    return t, Reader(t).pump(lambda r: r.of(p.HELLO))


# --- options ------------------------------------------------------------------


def test_default_options():
    assert parse_sim_url("sim") == SimOptions()
    assert parse_sim_url("sim?") == SimOptions()


def test_options_from_url():
    o = parse_sim_url("sim?latency_ms=8&drop=0.25&seed=3&color_order=rgb&led_count=12&protocol=2")
    assert (o.latency_ms, o.drop, o.seed, o.color_order, o.led_count, o.protocol) == (8.0, 0.25, 3, "RGB", 12, 2)


@pytest.mark.parametrize(
    "url, error",
    [
        ("simx", "not a sim URL"),
        ("/dev/ttyUSB0", "not a sim URL"),
        ("sim?speed=3", "unknown sim option 'speed'"),
        ("sim?drop=lots", "bad value"),
        ("sim?drop", "bad value"),
        ("sim?drop=1.5", "between 0 and 1"),
        ("sim?latency_ms=-1", "negative"),
        ("sim?led_count=0", "led_count"),
        ("sim?color_order=RRB", "color_order"),
    ],
)
def test_bad_options(url, error):
    with pytest.raises(ValueError, match=error):
        parse_sim_url(url)


# --- a healthy board ----------------------------------------------------------


def test_boots_with_text_then_hello():
    t, r = opened()
    assert p.parse_hello(r.of(p.HELLO)[0]) == (p.PROTOCOL_VERSION, (0, 0, 0), 10, "GRB")
    assert "rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)" in r.text
    assert t.board.boots == 1
    assert t.simulated is True


def test_ignores_input_while_booting():
    t = SimTransport.from_url("sim?boot_ms=100")
    t.open()
    t.write(p.encode(p.PING))  # main.py isn't running yet: lost, like on a real board
    r = Reader(t).pump(lambda r: r.of(p.HELLO))  # the HELLO it sends once booted
    r.feed(t.read(4096, 0.05))
    assert len(r.of(p.HELLO)) == 1
    assert t.board.pings == 0 and t.board.ignored_while_booting == len(p.encode(p.PING))


def test_ping_gets_hello():
    t, r = opened()
    t.write(p.encode(p.PING))
    r.pump(lambda r: len(r.of(p.HELLO)) == 2)
    assert t.board.pings == 1


def test_frame_gets_ack_after_the_latency():
    t, r = opened("sim?latency_ms=30")
    sent = time.monotonic()
    t.write(frame(42))
    r.pump(lambda r: r.of(p.ACK))
    assert time.monotonic() - sent >= 0.03
    assert p.parse_ack(r.of(p.ACK)[0]) == 42
    assert t.board.picture.matrix == MATRIX and t.board.picture.brightness == 9
    assert t.board.strip_rgb() == STRIP_RGB  # GRB on the wire, back to RGB


def test_frame_split_over_writes():
    t, r = opened()
    msg = frame(1)
    for b in msg:
        t.write(bytes([b]))
    r.pump(lambda r: r.of(p.ACK))
    assert t.board.frames_received == 1


def test_wrong_led_count_is_logged_not_shown():
    t, r = opened()
    t.write(frame(1, strip=bytes(3 * 7)))
    r.pump(lambda r: r.of(p.LOG))
    level, text = p.parse_log(r.of(p.LOG)[0])
    assert level == p.LOG_ERROR and "7 LEDs" in text and "has 10" in text
    assert t.board.picture is None and not r.of(p.ACK)


def test_unknown_message_type_is_logged():
    t, r = opened()
    t.write(p.encode(0x42, b"?"))
    r.pump(lambda r: r.of(p.LOG))
    assert p.parse_log(r.of(p.LOG)[0]) == (p.LOG_WARN, "unknown message type 0x42")


def test_repl_frame():
    t, r = opened()
    t.write(p.encode(p.REPL))
    r.pump(lambda r: r.of(p.LOG) and any("MicroPython" in line for line in r.text))
    assert p.parse_log(r.of(p.LOG)[0]) == (p.LOG_INFO, "entering repl")
    assert t.board.in_repl
    r.feed(r.t.read(4096, 0.05))
    assert r.lines.flush() == [">>>"]
    t.write(frame(1))  # the REPL ignores the protocol
    time.sleep(0.05)
    r.feed(t.read(4096, 0.01))
    assert not r.of(p.ACK)


def test_goes_idle_without_frames():
    t, r = opened("sim?idle_after_ms=100")
    assert t.board.idle  # nothing received yet
    t.write(frame(1))
    r.pump(lambda r: r.of(p.ACK))
    assert not t.board.idle
    time.sleep(0.12)
    assert t.board.idle


def test_read_waits_for_the_timeout_and_respects_max_bytes():
    t, r = opened()
    start = time.monotonic()
    assert t.read(4096, 0.05) == b""
    assert 0.04 <= time.monotonic() - start < 0.5
    t.write(p.encode(p.PING))
    time.sleep(0.02)
    first = t.read(3, 0.1)
    assert len(first) == 3
    r.feed(first + t.read(4096, 0.1))
    assert len(r.of(p.HELLO)) == 2  # nothing lost by reading in small pieces


def test_closed_port_raises():
    t, _ = opened()
    t.close()
    t.close()  # twice is fine
    with pytest.raises(TransportError):
        t.read(10, 0.01)
    with pytest.raises(TransportError):
        t.write(b"x")


def test_reopening_boots_again():
    t, _ = opened()
    t.close()
    t.open()
    Reader(t).pump(lambda r: r.of(p.HELLO))
    assert t.board.boots == 2


# --- faults -------------------------------------------------------------------


def test_drop_everything():
    t, r = opened("sim?drop=1")
    for seq in range(5):
        t.write(frame(seq))
    time.sleep(0.05)
    r.feed(t.read(4096, 0.01))
    assert not r.of(p.ACK)
    assert t.board.frames_dropped == 5 and t.board.picture is None


def acked_with(url, count=40):
    t, r = opened(url)
    for seq in range(count):
        t.write(frame(seq))
    time.sleep(0.05)
    r.pump(lambda r: True)
    r.feed(t.read(65536, 0.05))
    return [p.parse_ack(a) for a in r.of(p.ACK)]


def test_drop_is_repeatable_with_a_seed():
    first = acked_with("sim?drop=0.5&seed=7")
    assert first == acked_with("sim?drop=0.5&seed=7")
    assert 5 < len(first) < 35  # roughly half lost
    assert first != acked_with("sim?drop=0.5&seed=8")


def test_garbage_doesnt_lose_messages():
    t, r = opened("sim?garbage=1&seed=2")
    for seq in range(20):
        t.write(frame(seq))
    r.pump(lambda r: len(r.of(p.ACK)) == 20)
    assert [p.parse_ack(a) for a in r.of(p.ACK)] == list(range(20))
    assert r.parser.garbage_count > 20  # noise before every answer


def test_reboot_every():
    t, r = opened("sim?reboot_every=0.15")
    t.write(frame(1))
    r.pump(lambda r: r.of(p.ACK))
    r.pump(lambda r: len(r.of(p.HELLO)) == 2, timeout=1.0)  # HELLO without asking = rebooted
    assert t.board.boots == 2
    assert t.board.picture is None  # a reboot forgets the picture
    assert r.text.count("entry 0x400805b4") == 2


def test_unplug_every():
    t, r = opened("sim?unplug_every=0.1&unplug_for=0.2")
    with pytest.raises(TransportError, match="unplugged"):
        r.pump(lambda r: False, timeout=1.0)
    t.close()
    with pytest.raises(TransportError, match="unplugged"):
        t.open()  # still unplugged
    time.sleep(0.25)
    t.open()  # plugged back in: boots fresh
    Reader(t).pump(lambda r: r.of(p.HELLO))
    assert t.board.boots == 2


def test_other_protocol_version():
    _, r = opened("sim?protocol=2")
    assert p.hello_version(r.of(p.HELLO)[0]) == 2


def test_other_led_count_and_colour_order():
    _, r = opened("sim?led_count=12&color_order=RGB")
    assert p.parse_hello(r.of(p.HELLO)[0])[2:] == (12, "RGB")


# --- colour order -------------------------------------------------------------


def test_reorder():
    rgb = bytes([1, 2, 3, 4, 5, 6])
    assert reorder(rgb, "RGB", "GRB") == bytes([2, 1, 3, 5, 4, 6])
    assert reorder(rgb, "RGB", "BGR") == bytes([3, 2, 1, 6, 5, 4])
    assert reorder(reorder(rgb, "RGB", "BRG"), "BRG", "RGB") == rgb
    assert reorder(rgb, "RGB", "RGB") == rgb
    with pytest.raises(ValueError):
        reorder(rgb, "RGB", "RGG")
