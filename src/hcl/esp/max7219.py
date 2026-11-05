# The 8x8: one MAX7219 driving a single-colour matrix (docs/hcl.md 7.1).
# Write-only over SPI: 16 bits per register, CS low while they go out.
#
# Rows come as 8 bytes, row 0 at the top, bit 7 the leftmost pixel – the
# protocol's layout. MIRROR and FLIP turn that into how the module is mounted.

_DIGIT0 = 0x01  # rows: registers 1-8
_DECODE_MODE = 0x09
_INTENSITY = 0x0A
_SCAN_LIMIT = 0x0B
_SHUTDOWN = 0x0C
_DISPLAY_TEST = 0x0F


def _reverse(b):
    b = ((b & 0xF0) >> 4) | ((b & 0x0F) << 4)
    b = ((b & 0xCC) >> 2) | ((b & 0x33) << 2)
    return ((b & 0xAA) >> 1) | ((b & 0x55) << 1)


class Matrix:
    def __init__(self, spi, cs, mirror=False, flip=False):
        self._spi = spi
        self._cs = cs
        self._mirror = mirror
        self._flip = flip
        self._buf = bytearray(2)
        self._rows = bytearray(8)
        self._brightness = -1
        self.setup()

    def _write(self, register, value):
        self._buf[0] = register
        self._buf[1] = value
        self._cs.value(0)
        self._spi.write(self._buf)
        self._cs.value(1)

    def setup(self):
        """Every register the chip needs. Sent again every few seconds, so a
        replugged or glitched module recovers by itself."""
        self._write(_SHUTDOWN, 0)
        self._write(_DISPLAY_TEST, 0)
        self._write(_DECODE_MODE, 0)  # raw pixels, no 7-segment digits
        self._write(_SCAN_LIMIT, 7)  # all 8 rows
        self._write(_INTENSITY, max(0, self._brightness))
        for i in range(8):
            self._write(_DIGIT0 + i, self._rows[i])
        self._write(_SHUTDOWN, 1)

    def show(self, rows, brightness):
        """8 row bytes and a brightness 0-15. Only what changed is sent."""
        if brightness != self._brightness:
            self._brightness = brightness
            self._write(_INTENSITY, brightness)
        for i in range(8):
            b = rows[7 - i if self._flip else i]
            if self._mirror:
                b = _reverse(b)
            if b != self._rows[i]:
                self._rows[i] = b
                self._write(_DIGIT0 + i, b)
