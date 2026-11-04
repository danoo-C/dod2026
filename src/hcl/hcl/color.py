"""Colour order of LED strips. The backend always works in RGB; most WS2812B
strips want GRB on the wire (docs/hcl.md 3.2)."""


def reorder(strip: bytes, from_order: str, to_order: str) -> bytes:
    """Rearrange the 3 bytes of every LED, e.g. from "RGB" to "GRB"."""
    if sorted(from_order) != ["B", "G", "R"] or sorted(to_order) != ["B", "G", "R"]:
        raise ValueError(f"colour orders must be a mix of R, G and B, got {from_order!r} and {to_order!r}")
    if from_order == to_order:
        return bytes(strip)
    out = bytearray(len(strip))
    for i, channel in enumerate(to_order):
        src = from_order.index(channel)
        out[i::3] = strip[src::3]
    return bytes(out)
