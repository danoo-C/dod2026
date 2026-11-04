import ast
import random
from pathlib import Path

import pytest

from hcl import protocol as p

STRIP = bytes(range(30))  # 10 LEDs
MATRIX = bytes([0x81, 0x42, 0x24, 0x18, 0x18, 0x24, 0x42, 0x81])


def frame_msg(seq=7):
    return p.encode(p.FRAME, p.frame_payload(seq, STRIP, MATRIX, 8))


def parse_all(data, parser=None):
    parser = parser or p.Parser()
    return parser.feed(data), parser


# --- encoding -------------------------------------------------------------


def test_encode_layout_and_checksum():
    msg = p.encode(p.ACK, b"\x05")
    assert msg[:2] == p.MAGIC
    assert msg[2] == p.ACK
    assert msg[3:5] == b"\x01\x00"  # length 1, little endian
    assert msg[5:6] == b"\x05"
    assert msg[6] == (p.ACK + 1 + 0 + 5) & 0xFF


def test_encode_empty_payload():
    assert p.encode(p.PING) == p.MAGIC + bytes([p.PING, 0, 0, p.PING])


def test_encode_limits():
    assert len(p.encode(p.LOG, bytes(p.MAX_PAYLOAD))) == p.HEADER_SIZE + p.MAX_PAYLOAD + 1
    with pytest.raises(ValueError, match="too long"):
        p.encode(p.LOG, bytes(p.MAX_PAYLOAD + 1))
    with pytest.raises(ValueError, match="type"):
        p.encode(0x100)


# --- round trips ----------------------------------------------------------


def test_round_trip_every_type():
    messages = [
        (p.FRAME, p.frame_payload(3, STRIP, MATRIX, 15)),
        (p.PING, b""),
        (p.REPL, b""),
        (p.HELLO, p.hello_payload((1, 2, 3), 10, "GRB")),
        (p.ACK, p.ack_payload(3)),
        (p.LOG, p.log_payload(p.LOG_WARN, "matrix not found")),
    ]
    stream = b"".join(p.encode(t, pl) for t, pl in messages)
    got, parser = parse_all(stream)
    assert got == messages
    assert parser.garbage_count == 0
    assert parser.pending() == 0


def test_frame_payload_round_trip():
    seq, strip, matrix, brightness = p.parse_frame(p.frame_payload(300, STRIP, MATRIX, 4))
    assert (seq, strip, matrix, brightness) == (300 & 0xFF, STRIP, MATRIX, 4)
    assert len(p.frame_payload(0, STRIP, MATRIX, 0)) == 40  # hcl.md 5.2: 40 bytes for 10 LEDs
    assert len(frame_msg()) == 46


@pytest.mark.parametrize(
    "strip, matrix, brightness, error",
    [
        (bytes(29), MATRIX, 8, "multiple of 3"),
        (STRIP, bytes(7), 8, "matrix"),
        (STRIP, MATRIX, 16, "brightness"),
        (STRIP, MATRIX, -1, "brightness"),
        (bytes(3 * 200), MATRIX, 8, "too many LEDs"),
    ],
)
def test_frame_payload_rejects(strip, matrix, brightness, error):
    with pytest.raises(ValueError, match=error):
        p.frame_payload(0, strip, matrix, brightness)


def test_parse_frame_rejects_bad_payloads():
    with pytest.raises(ValueError):
        p.parse_frame(bytes(9))  # shorter than the fixed part
    with pytest.raises(ValueError):
        p.parse_frame(bytes(11))  # strip not a multiple of 3
    with pytest.raises(ValueError):
        p.parse_frame(bytes(10)[:-1] + b"\x10")  # brightness 16


def test_hello_round_trip():
    payload = p.hello_payload((1, 0, 3), 10, "GRB")
    assert len(payload) == p.HELLO_SIZE == 9
    assert p.parse_hello(payload) == (p.PROTOCOL_VERSION, (1, 0, 3), 10, "GRB")
    assert p.hello_version(payload) == p.PROTOCOL_VERSION


def test_hello_version_of_unknown_layout():
    # a future board might send a longer HELLO; the version must still be readable
    future = bytes([2]) + bytes(20)
    assert p.hello_version(future) == 2
    with pytest.raises(ValueError):
        p.parse_hello(future)


def test_hello_rejects_bad_colour_order():
    with pytest.raises(ValueError, match="colour order"):
        p.hello_payload((1, 0, 0), 10, "RRB")


def test_ack_and_log():
    assert p.parse_ack(p.ack_payload(256 + 9)) == 9
    with pytest.raises(ValueError):
        p.parse_ack(b"")
    assert p.parse_log(p.log_payload(p.LOG_ERROR, "chyba: žiadna matica")) == (p.LOG_ERROR, "chyba: žiadna matica")


def test_long_log_is_cut_to_fit():
    payload = p.log_payload(p.LOG_INFO, "x" * 2000)
    assert len(payload) == p.MAX_PAYLOAD
    p.encode(p.LOG, payload)  # fits into one message


# --- parsing a messy stream -----------------------------------------------


def test_one_byte_at_a_time():
    parser = p.Parser()
    got = []
    for b in frame_msg() + frame_msg(8):
        got += parser.feed(bytes([b]))
    assert [p.parse_frame(pl)[0] for _, pl in got] == [7, 8]
    assert parser.garbage_count == 0


def test_garbage_before_and_between():
    stream = b"boot noise\r\n" + frame_msg(1) + b"\x00\xff\x13" + frame_msg(2)
    got, parser = parse_all(stream)
    assert [p.parse_frame(pl)[0] for _, pl in got] == [1, 2]
    assert parser.garbage_count == len(b"boot noise\r\n") + 3
    assert parser.take_garbage() == b"boot noise\r\n\x00\xff\x13"
    assert parser.take_garbage() == b""


def test_garbage_inside_a_message_loses_only_that_message():
    broken = frame_msg(1)
    broken = broken[:20] + b"\x99\x99" + broken[20:]
    got, parser = parse_all(broken + frame_msg(2))
    assert [p.parse_frame(pl)[0] for _, pl in got] == [2]
    assert parser.garbage_count == len(broken)


def test_wrong_checksum_is_dropped():
    bad = bytearray(frame_msg(1))
    bad[-1] ^= 0xFF
    got, _ = parse_all(bytes(bad) + frame_msg(2))
    assert [p.parse_frame(pl)[0] for _, pl in got] == [2]


def test_corrupted_type_is_caught_by_the_checksum():
    # With a checksum over the payload only, this would parse as a PING.
    bad = bytearray(frame_msg(1))
    bad[2] = p.PING
    got, _ = parse_all(bytes(bad) + frame_msg(2))
    assert [p.parse_frame(pl)[0] for _, pl in got] == [2]


def test_corrupted_length_is_caught_by_the_checksum():
    # Length 4 -> 3 makes the last zero of the payload pose as the checksum;
    # a checksum over the payload only (0) would accept it.
    bad = bytearray(p.encode(p.LOG, bytes(4)))
    bad[3] = 3
    got, parser = parse_all(bytes(bad) + frame_msg(2))
    assert [t for t, _ in got] == [p.FRAME]
    assert parser.garbage_count == len(bad)


def test_oversized_length_resyncs():
    bogus = p.MAGIC + bytes([p.FRAME]) + (p.MAX_PAYLOAD + 1).to_bytes(2, "little")
    got, _ = parse_all(bogus + frame_msg(2))
    assert [p.parse_frame(pl)[0] for _, pl in got] == [2]


def test_message_hidden_in_a_truncated_one_is_found():
    # The first message is cut off; its length makes the parser read into the
    # second one. When the checksum fails, the second one must still be found.
    truncated = frame_msg(1)[:12]
    got, _ = parse_all(truncated + frame_msg(2))
    assert [p.parse_frame(pl)[0] for _, pl in got] == [2]


def test_magic_bytes_inside_a_payload():
    payload = p.MAGIC * 10
    got, parser = parse_all(p.encode(p.LOG, payload))
    assert got == [(p.LOG, payload)]
    assert parser.garbage_count == 0


def test_doubled_first_magic_byte():
    got, parser = parse_all(b"\xa5" + frame_msg(4))
    assert [p.parse_frame(pl)[0] for _, pl in got] == [4]
    assert parser.garbage_count == 1


def test_trailing_first_magic_byte_waits_for_more():
    msg = frame_msg(5)
    parser = p.Parser()
    assert parser.feed(b"xyz" + msg[:1]) == []
    assert parser.pending() == 1  # the A5 is kept, not counted as garbage
    assert parser.garbage_count == 3
    assert len(parser.feed(msg[1:])) == 1


def test_reset_partial():
    parser = p.Parser()
    assert parser.feed(frame_msg()[:20]) == []
    assert parser.pending() == 20
    assert parser.reset_partial() == 20
    assert parser.pending() == 0
    assert parser.garbage_count == 20
    assert len(parser.feed(frame_msg())) == 1


def test_kept_garbage_is_capped():
    parser = p.Parser(keep_garbage=16)
    parser.feed(bytes(range(100)))
    assert parser.garbage_count == 100
    assert parser.take_garbage() == bytes(range(84, 100))


def test_board_keeps_no_garbage():
    parser = p.Parser(keep_garbage=0)
    parser.feed(b"noise" * 100)
    assert parser.garbage_count == 500
    assert parser.take_garbage() == b""


def test_random_noise_between_messages():
    rng = random.Random(2026)
    stream = b""
    for seq in range(200):
        stream += bytes(rng.randrange(256) for _ in range(rng.randrange(0, 12)))
        stream += frame_msg(seq)
    parser = p.Parser()
    got = []
    pos = 0
    while pos < len(stream):  # random chunk sizes, like reads from a port
        n = rng.randrange(1, 64)
        got += parser.feed(stream[pos : pos + n])
        pos += n
    seqs = [p.parse_frame(pl)[0] for t, pl in got if t == p.FRAME]
    # The seed is fixed, so this is exact: every frame comes through, in order.
    assert seqs == list(range(200))


# --- MicroPython compatibility guard (hcl.md 5.5) --------------------------

PROTOCOL_SOURCE = Path(p.__file__).read_text(encoding="utf-8")


def test_protocol_imports_only_struct():
    tree = ast.parse(PROTOCOL_SOURCE)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert imported == {"struct"}


def test_protocol_avoids_what_micropython_lacks():
    tree = ast.parse(PROTOCOL_SOURCE)
    for node in ast.walk(tree):
        assert not isinstance(node, ast.JoinedStr), f"f-string on line {node.lineno}"
        assert not isinstance(node, ast.AnnAssign), f"annotation on line {node.lineno}"
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.returns is None, f"return annotation in {node.name}"
            assert all(a.annotation is None for a in node.args.args), f"argument annotation in {node.name}"
            assert not node.decorator_list, f"decorator on {node.name}"
        if isinstance(node, ast.ClassDef):
            assert not node.decorator_list, f"decorator on {node.name}"
