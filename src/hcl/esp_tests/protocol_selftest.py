# The protocol on MicroPython (HCL plan, stage 2 step 2): every message type
# encoded and parsed with the board's own copy of protocol.py – the real
# check that hcl/protocol.py only uses what MicroPython has.
#
#   ./dod esp upload                                  (puts protocol.py on the board)
#   ./dod esp run src/hcl/esp_tests/protocol_selftest.py
#
# Prints one line per check and PASS or FAIL at the end. It runs with
# mpremote (prints are fine here: this isn't main.py).

import protocol as p

failed = []


def check(name, cond):
    print(("ok    " if cond else "FAIL  ") + name)
    if not cond:
        failed.append(name)


def roundtrip(type_, payload):
    parser = p.Parser()
    got = parser.feed(p.encode(type_, payload))
    return got == [(type_, payload)]


strip = bytes(range(30))
frame = p.frame_payload(7, strip, bytes(range(0xF8, 0x100)), 15)
check("FRAME round trip", roundtrip(p.FRAME, frame))
seq, s, rows, brightness = p.parse_frame(frame)
check("FRAME fields", seq == 7 and s == strip and rows == bytes(range(0xF8, 0x100)) and brightness == 15)
check("PING round trip", roundtrip(p.PING, b""))
check("REPL round trip", roundtrip(p.REPL, b""))
hello = p.hello_payload((1, 0, 0), 10, "GRB")
check("HELLO round trip", roundtrip(p.HELLO, hello))
check("HELLO fields", p.parse_hello(hello) == (p.PROTOCOL_VERSION, (1, 0, 0), 10, "GRB"))
check("ACK round trip", roundtrip(p.ACK, p.ack_payload(300)) and p.parse_ack(p.ack_payload(300)) == 300 & 0xFF)
log = p.log_payload(p.LOG_WARN, "žltý kôň")  # UTF-8, as the board sends it
check("LOG round trip", roundtrip(p.LOG, log) and p.parse_log(log) == (p.LOG_WARN, "žltý kôň"))
every_byte = bytes(range(256))
check("all 256 byte values in a payload", roundtrip(p.FRAME, every_byte[:255] + b"\x00"))

# the parser finds messages behind garbage, a broken message and a split
parser = p.Parser(keep_garbage=0)
good = p.encode(p.ACK, b"\x05")
broken = bytearray(p.encode(p.ACK, b"\x06"))
broken[-1] ^= 0xFF
got = parser.feed(b"junk\xa5" + bytes(broken) + good[:3])
got += parser.feed(good[3:])
check("resync after garbage and a bad checksum", got == [(p.ACK, b"\x05")] and parser.garbage_count > 0)
try:
    p.encode(p.LOG, bytes(p.MAX_PAYLOAD + 1))
    check("a payload over 512 bytes is refused", False)
except ValueError:
    check("a payload over 512 bytes is refused", True)

print("PASS" if not failed else "FAIL: " + ", ".join(failed))
