"""./dod hcl repl – ask main.py on the board to step aside, so mpremote can take over.

main.py turns Ctrl-C off (it would break binary frames), so mpremote can't
interrupt it. This sends the REPL message instead (docs/hcl.md 5.2, 9).
Opening the port can reset the board, so it first waits until main.py
answers a PING, then sends REPL and waits for main.py to confirm.

Exit codes: 0 the board is at the REPL now, 1 no port, 2 main.py didn't answer
(the board may already be at the >>> prompt; mpremote will work then too).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable

from hcl import protocol
from hcl.connect import open_transport
from hcl.rawtext import LineCollector
from hcl.tools.common import EXIT_FAIL, EXIT_OK, EXIT_USAGE, make_parser
from hcl.transport import Transport, TransportError

EXIT_NO_ANSWER = 2
HELLO_TIMEOUT = 5.0  # long enough for a board that resets when the port opens
CONFIRM_TIMEOUT = 2.0
PING_EVERY = 0.5


def repl(transport: Transport, out: Callable[[str], None] = print) -> int:
    try:
        transport.open()
    except TransportError as e:
        out(f"can't open the port: {e}")
        return EXIT_FAIL
    parser = protocol.Parser()
    lines = LineCollector()

    def read_until(found: Callable[[int, bytes], bool], timeout: float, ping: bool) -> bool:
        deadline = time.monotonic() + timeout
        next_ping = 0.0
        while time.monotonic() < deadline:
            if ping and time.monotonic() >= next_ping:
                transport.write(protocol.encode(protocol.PING))
                next_ping = time.monotonic() + PING_EVERY
            data = transport.read(4096, 0.05)
            hit = False
            for type_, payload in parser.feed(data):
                if type_ == protocol.LOG:
                    out(f"board says: {protocol.parse_log(payload)[1]}")
                hit = hit or found(type_, payload)
            for line in lines.feed(parser.take_garbage()):
                out(f"board prints: {line}")
            if hit:
                return True
        for line in lines.flush():
            out(f"board prints: {line}")
        return False

    try:
        if not read_until(lambda t, _: t == protocol.HELLO, HELLO_TIMEOUT, ping=True):
            out(f"main.py didn't answer within {HELLO_TIMEOUT:g} s. If the board is already at the >>> prompt, "
                "that's fine. If not: press EN, release it, then hold BOOT for 1 s (docs/hcl.md 9).")
            return EXIT_NO_ANSWER
        transport.write(protocol.encode(protocol.REPL))
        confirmed = read_until(
            lambda t, p: t == protocol.LOG and protocol.parse_log(p)[1] == "entering repl", CONFIRM_TIMEOUT, ping=False)
        # the REPL banner and prompt follow the confirmation
        read_until(lambda t, p: False, 0.3, ping=False)
        if not confirmed:
            out("main.py answered PING but didn't confirm the REPL message; try again, or use the BOOT button.")
            return EXIT_NO_ANSWER
        out("the board is at the REPL now; mpremote can take over")
        return EXIT_OK
    except TransportError as e:
        out(f"lost the port: {e}")
        return EXIT_FAIL
    finally:
        transport.close()


def main(argv: list[str] | None = None) -> int:
    p = make_parser("repl", __doc__.splitlines()[0])
    args: argparse.Namespace = p.parse_args(argv)
    try:
        transport = open_transport(args.url, baud=args.baud)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    try:
        return repl(transport)
    except KeyboardInterrupt:
        transport.close()
        print("\nstopped", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
