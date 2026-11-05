# DOD 2026 – the board: frames from the backend onto the strip and the 8x8
# (docs/hcl.md 7.2). A dumb bridge: it shows what it gets, says what it shows
# (ACK), and when nothing comes for a while plays its own idle animation.
#
# The USB port is also the REPL, so: no print() ever (everything goes out as
# LOG messages), and Ctrl-C is off while this runs – a 0x03 byte inside a
# frame would stop it. To get to the REPL: the REPL message
# (./dod hcl repl), or hold BOOT during the first second after a reset.

import math
import select
import sys
import time

import machine
import micropython
import neopixel

import config as c
import protocol as p
from max7219 import Matrix

SETUP_EVERY_MS = 5000  # the MAX7219's registers again
STALE_MS = 50  # a half message older than this is dropped (like the host)
IDLE_STEP_MS = 40  # the idle animation's frame time


class Board:
    def __init__(self):
        self.out = sys.stdout.buffer
        self.inp = sys.stdin.buffer
        self.poll = select.poll()
        self.poll.register(sys.stdin, select.POLLIN)
        self.np = neopixel.NeoPixel(machine.Pin(c.STRIP_PIN, machine.Pin.OUT), c.LED_COUNT)
        # frames arrive already in COLOR_ORDER and go into the buffer as they are;
        # the idle animation sets (R, G, B) through NeoPixel, which must use the same order
        self.np.ORDER = (c.COLOR_ORDER.index("R"), c.COLOR_ORDER.index("G"), c.COLOR_ORDER.index("B"), 3)
        spi = machine.SPI(c.SPI_ID, baudrate=c.SPI_BAUD, polarity=0, phase=0,
                          sck=machine.Pin(c.MATRIX_CLK), mosi=machine.Pin(c.MATRIX_DIN),
                          miso=machine.Pin(c.SPI_MISO_UNUSED))
        cs = machine.Pin(c.MATRIX_CS, machine.Pin.OUT, value=1)
        self.matrix = Matrix(spi, cs, mirror=c.MATRIX_MIRROR, flip=c.MATRIX_FLIP)
        self.strip_size = c.LED_COUNT * 3
        # the message being received: a small state machine, one byte at a time
        self.state = 0  # 0 looking for A5, 1 got A5, 2 header, 3 payload + checksum
        self.head = bytearray(3)
        self.body = bytearray(p.MAX_PAYLOAD + 1)
        self.got = 0
        self.need = 0
        self.started = 0
        self.last_frame = time.ticks_ms()
        self.last_setup = time.ticks_ms()
        self.idle_at = 0
        self.running = True

    # --- talking to the host

    def send(self, type_, payload=b""):
        self.out.write(p.encode(type_, payload))

    def log(self, level, text):
        self.send(p.LOG, p.log_payload(level, text))

    def hello(self):
        self.send(p.HELLO, p.hello_payload(c.FIRMWARE, c.LED_COUNT, c.COLOR_ORDER))

    # --- receiving

    def pump(self):
        """Everything that has arrived, byte by byte; whole messages are handled."""
        if self.state and time.ticks_diff(time.ticks_ms(), self.started) > STALE_MS:
            self.state = 0  # a half message that never finished
        while self.poll.poll(0):
            b = self.inp.read(1)
            if not b:
                return
            self.byte(b[0])

    def byte(self, x):
        s = self.state
        if s == 0:
            if x == 0xA5:
                self.state = 1
                self.started = time.ticks_ms()
        elif s == 1:
            if x == 0x5A:
                self.state = 2
                self.got = 0
            elif x != 0xA5:
                self.state = 0
        elif s == 2:
            self.head[self.got] = x
            self.got += 1
            if self.got == 3:
                n = self.head[1] | (self.head[2] << 8)
                if n > p.MAX_PAYLOAD:
                    self.state = 0
                    return
                self.need = n + 1  # the payload and the checksum
                self.got = 0
                self.state = 3
        else:
            self.body[self.got] = x
            self.got += 1
            if self.got == self.need:
                self.state = 0
                n = self.need - 1
                payload = bytes(self.body[:n])
                if self.body[n] == p.checksum(self.head[0], n, payload):
                    self.handle(self.head[0], payload)

    def handle(self, type_, payload):
        if type_ == p.FRAME:
            seq, strip, rows, brightness = p.parse_frame(payload)
            if len(strip) != self.strip_size:
                self.log(p.LOG_WARN, "frame for %d LEDs, this board has %d" % (len(strip) // 3, c.LED_COUNT))
                return
            self.np.buf[:] = strip
            self.np.write()
            self.matrix.show(rows, brightness)
            self.send(p.ACK, p.ack_payload(seq))
            self.last_frame = time.ticks_ms()
        elif type_ == p.PING:
            self.hello()
        elif type_ == p.REPL:
            self.log(p.LOG_INFO, "entering repl")
            self.running = False
        else:
            self.log(p.LOG_WARN, "unknown message type 0x%02x" % type_)

    # --- when the backend is quiet

    def idle(self, now):
        """Slow breathing on the strip, a dot circling the 8x8's edge."""
        if time.ticks_diff(now, self.idle_at) < IDLE_STEP_MS:
            return
        self.idle_at = now
        t = time.ticks_diff(now, self.last_frame) / 1000
        level = int(4 + 28 * (1 - math.cos(t * 2 * math.pi / 6)) / 2)  # dim: at most 32 of 255
        for i in range(c.LED_COUNT):
            self.np[i] = (level // 3, level // 2, level)  # a soft blue, in (R, G, B): NeoPixel orders it
        self.np.write()
        step = int(t / 0.15) % 28
        rows = bytearray(8)
        x, y = _edge(step)
        rows[y] = 0x80 >> x
        self.matrix.show(rows, 1)

    # --- the loop

    def run(self):
        # the host PINGs every 500 ms while it waits; during the boot and the BOOT
        # button's second they piled up. One HELLO answers them all.
        while self.poll.poll(0):
            self.inp.read(1)
        self.hello()
        while self.running:
            try:
                self.pump()
                now = time.ticks_ms()
                if time.ticks_diff(now, self.last_frame) > c.IDLE_AFTER_MS:
                    self.idle(now)
                if time.ticks_diff(now, self.last_setup) > SETUP_EVERY_MS:
                    self.last_setup = now
                    self.matrix.setup()
                if not self.poll.poll(2):  # wait for bytes, briefly, so the loop doesn't spin
                    pass
            except Exception as e:  # a bug or a bad frame: say so, keep going
                self.state = 0
                self.log(p.LOG_ERROR, "%s: %s" % (type(e).__name__, e))


def _edge(step):
    """The 28 pixels around the 8x8's edge, clockwise from the top left."""
    if step < 8:
        return step, 0
    if step < 15:
        return 7, step - 7
    if step < 22:
        return 7 - (step - 14), 7
    return 0, 7 - (step - 21)


def main():
    button = machine.Pin(c.BOOT_BUTTON, machine.Pin.IN, machine.Pin.PULL_UP)
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < 1000:
        if button.value() == 0:
            return  # BOOT held: stay at the REPL
        time.sleep_ms(20)
    micropython.kbd_intr(-1)
    try:
        Board().run()
    finally:
        micropython.kbd_intr(3)  # the REPL message, or something escaped: Ctrl-C works again


main()
