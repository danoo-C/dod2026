# The strip alone, straight from the board – no host, no protocol (HCL plan,
# stage 2 step 3). If these colours are wrong, the problem is the wiring or
# the data signal, not the software.
#
#   ./dod esp run src/hcl/esp_tests/strip_test.py
#
# Each step prints what you should see, then holds it for 4 seconds.

import time

import machine
import neopixel

import config as c

np = neopixel.NeoPixel(machine.Pin(c.STRIP_PIN, machine.Pin.OUT), c.LED_COUNT)
np.ORDER = (c.COLOR_ORDER.index("R"), c.COLOR_ORDER.index("G"), c.COLOR_ORDER.index("B"), 3)

STEPS = [
    ("1. all OFF (dark)", [(0, 0, 0)] * c.LED_COUNT),
    ("2. only the FIRST LED (at the wire) RED, the rest dark", [(80, 0, 0)] + [(0, 0, 0)] * (c.LED_COUNT - 1)),
    ("3. all RED", [(80, 0, 0)] * c.LED_COUNT),
    ("4. all GREEN", [(0, 80, 0)] * c.LED_COUNT),
    ("5. all BLUE", [(0, 0, 80)] * c.LED_COUNT),
    ("6. red, green, blue, red, green, blue, ... along the strip",
     [((80, 0, 0), (0, 80, 0), (0, 0, 80))[i % 3] for i in range(c.LED_COUNT)]),
    ("7. all OFF again", [(0, 0, 0)] * c.LED_COUNT),
]

print("strip on GPIO%d, %d LEDs, colour order %s" % (c.STRIP_PIN, c.LED_COUNT, c.COLOR_ORDER))
for text, colours in STEPS:
    print(text)
    for i, colour in enumerate(colours):
        np[i] = colour
    np.write()
    time.sleep(4)
print("done")
