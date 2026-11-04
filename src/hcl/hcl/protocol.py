"""Serial protocol between the host and the ESP32 (docs/hcl.md, section 5).

This file also runs on the board: `./dod esp upload` copies it there. So it
only uses what MicroPython has too: no dataclasses, typing, enum, type
annotations or f-strings, and no module except `struct`.

Every message, in both directions:

    A5 5A | type (1) | length (2, little endian) | payload | checksum (1)

    checksum = (type + length_lo + length_hi + sum(payload)) & 0xFF
"""

import struct

PROTOCOL_VERSION = 1

MAGIC = b"\xa5\x5a"
HEADER_SIZE = 5  # magic (2), type (1), length (2)
MAX_PAYLOAD = 512

# message types, host -> board
FRAME = 0x01
PING = 0x02
REPL = 0x7F
# message types, board -> host
HELLO = 0x81
ACK = 0x82
LOG = 0x83

# LOG levels
LOG_INFO = 0
LOG_WARN = 1
LOG_ERROR = 2

MATRIX_ROWS = 8
MAX_BRIGHTNESS = 15
# a FRAME payload is seq (1), strip (3 per LED), matrix (8), brightness (1)
FRAME_FIXED = 1 + MATRIX_ROWS + 1

# HELLO payload: protocol version, firmware major, minor, patch, LED count, colour order
_HELLO = "<BBBBH3s"
HELLO_SIZE = struct.calcsize(_HELLO)


def checksum(type_, length, payload):
    return (type_ + (length & 0xFF) + (length >> 8) + sum(payload)) & 0xFF


def encode(type_, payload=b""):
    """One message, ready to write to the port."""
    if not 0 <= type_ <= 0xFF:
        raise ValueError("message type out of range: %r" % (type_,))
    n = len(payload)
    if n > MAX_PAYLOAD:
        raise ValueError("payload too long: %d bytes, max %d" % (n, MAX_PAYLOAD))
    return MAGIC + struct.pack("<BH", type_, n) + bytes(payload) + bytes((checksum(type_, n, payload),))


class Parser:
    """Turns a stream of bytes into messages.

    feed() returns the messages completed so far, as (type, payload) pairs.
    Bytes that belong to no message are garbage: they are counted in
    garbage_count, and the last `keep_garbage` of them can be fetched with
    take_garbage(). The host turns readable garbage into text lines (a
    MicroPython traceback, for example); the board keeps none.

    On any mismatch (oversized length, wrong checksum) only the first byte of
    the attempt is dropped and the search goes on from the next one, so a
    real message hidden inside a broken one is still found.
    """

    def __init__(self, keep_garbage=1024):
        self._buf = b""
        self._keep = keep_garbage
        self._garbage = b""
        self.garbage_count = 0
        self.message_count = 0

    def feed(self, data):
        if data:
            self._buf = self._buf + bytes(data)
        buf = self._buf
        out = []
        while buf:
            start = buf.find(MAGIC)
            if start < 0:
                # a last A5 may be the first half of the next message's magic
                keep = 1 if buf[-1:] == MAGIC[:1] else 0
                self._drop(buf[: len(buf) - keep])
                buf = buf[len(buf) - keep :]
                break
            if start:
                self._drop(buf[:start])
                buf = buf[start:]
            if len(buf) < HEADER_SIZE:
                break
            type_, n = struct.unpack("<BH", buf[2:HEADER_SIZE])
            if n > MAX_PAYLOAD:
                self._drop(buf[:1])
                buf = buf[1:]
                continue
            end = HEADER_SIZE + n
            if len(buf) < end + 1:
                break
            payload = buf[HEADER_SIZE:end]
            if buf[end] == checksum(type_, n, payload):
                out.append((type_, payload))
                self.message_count += 1
                buf = buf[end + 1 :]
            else:
                self._drop(buf[:1])
                buf = buf[1:]
        self._buf = buf
        return out

    def pending(self):
        """Bytes waiting for the rest of a message."""
        return len(self._buf)

    def reset_partial(self):
        """Give up on a half-received message (the host does this after 50 ms).
        Its bytes count as garbage. Returns how many were dropped."""
        n = len(self._buf)
        self._drop(self._buf)
        self._buf = b""
        return n

    def take_garbage(self):
        """The garbage kept since the last call."""
        g = self._garbage
        self._garbage = b""
        return g

    def _drop(self, chunk):
        if not chunk:
            return
        self.garbage_count += len(chunk)
        if self._keep:
            self._garbage = (self._garbage + chunk)[-self._keep :]


# --- payloads -------------------------------------------------------------


def frame_payload(seq, strip, matrix, brightness):
    """FRAME: strip is 3 bytes per LED in the board's colour order,
    matrix is 8 rows (row 0 = top, bit 7 = leftmost pixel)."""
    if len(strip) % 3:
        raise ValueError("strip length must be a multiple of 3, got %d" % len(strip))
    if len(matrix) != MATRIX_ROWS:
        raise ValueError("matrix must be %d bytes, got %d" % (MATRIX_ROWS, len(matrix)))
    if not 0 <= brightness <= MAX_BRIGHTNESS:
        raise ValueError("brightness must be 0-%d, got %r" % (MAX_BRIGHTNESS, brightness))
    payload = bytes((seq & 0xFF,)) + bytes(strip) + bytes(matrix) + bytes((brightness,))
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("too many LEDs for one FRAME: %d" % (len(strip) // 3))
    return payload


def parse_frame(payload):
    """FRAME -> (seq, strip, matrix, brightness)."""
    n = len(payload) - FRAME_FIXED
    if n < 0 or n % 3:
        raise ValueError("bad FRAME payload length: %d" % len(payload))
    brightness = payload[-1]
    if brightness > MAX_BRIGHTNESS:
        raise ValueError("bad FRAME brightness: %d" % brightness)
    return payload[0], payload[1 : 1 + n], payload[1 + n : 1 + n + MATRIX_ROWS], brightness


def hello_payload(firmware, led_count, color_order):
    """HELLO: firmware is (major, minor, patch), color_order like "GRB"."""
    order = color_order.encode() if isinstance(color_order, str) else bytes(color_order)
    if sorted(order) != sorted(b"RGB"):
        raise ValueError("colour order must be a mix of R, G and B, got %r" % (color_order,))
    return struct.pack(_HELLO, PROTOCOL_VERSION, firmware[0], firmware[1], firmware[2], led_count, order)


def hello_version(payload):
    """The protocol version from a HELLO, readable even if the rest of the
    payload has a layout from another version."""
    if not payload:
        raise ValueError("empty HELLO")
    return payload[0]


def parse_hello(payload):
    """HELLO -> (protocol version, (major, minor, patch), LED count, colour order)."""
    if len(payload) != HELLO_SIZE:
        raise ValueError("bad HELLO payload length: %d" % len(payload))
    version, major, minor, patch, leds, order = struct.unpack(_HELLO, payload)
    return version, (major, minor, patch), leds, order.decode()


def ack_payload(seq):
    return bytes((seq & 0xFF,))


def parse_ack(payload):
    """ACK -> seq."""
    if len(payload) != 1:
        raise ValueError("bad ACK payload length: %d" % len(payload))
    return payload[0]


def log_payload(level, text):
    """LOG: the text is cut to fit into one message."""
    return bytes((level,)) + text.encode("utf-8")[: MAX_PAYLOAD - 1]


def parse_log(payload):
    """LOG -> (level, text). Only the host calls this."""
    if not payload:
        raise ValueError("empty LOG")
    return payload[0], payload[1:].decode("utf-8", "replace")
