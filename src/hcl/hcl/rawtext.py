"""Readable text among the bytes that were not part of any message.

When main.py crashes, MicroPython prints the traceback on the same port as
the messages, and the board prints a banner when it boots. This turns such
text into lines (the RawText event, docs/hcl.md 3.5), and drops binary noise.
Host only, unlike protocol.py.
"""

PRINTABLE_SHARE = 0.9  # a line with less printable text than this is noise


class LineCollector:
    def __init__(self, max_line: int = 200) -> None:
        self._partial = bytearray()
        self._max = max_line

    def feed(self, data: bytes) -> list[str]:
        """The lines completed by `data`. A line longer than max_line is cut
        into pieces, so a stream without newlines can't grow forever."""
        lines = []
        for b in data:
            if b == 0x0A:
                lines.append(self._take())
            else:
                self._partial.append(b)
                if len(self._partial) >= self._max:
                    lines.append(self._take())
        return [line for line in lines if line is not None]

    def flush(self) -> list[str]:
        """The unfinished line, if it is text (like MicroPython's '>>> ' prompt)."""
        line = self._take()
        return [line] if line is not None else []

    def _take(self) -> str | None:
        raw = bytes(self._partial)
        self._partial.clear()
        try:
            text = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            return None
        if not text:
            return None
        printable = sum(ch.isprintable() for ch in text)
        return text if printable / len(text) >= PRINTABLE_SHARE else None
