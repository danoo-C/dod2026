# The board's wiring and settings (docs/hcl.md 7.1). After changing it:
# ./dod esp upload.

FIRMWARE = (1, 0, 0)

# the strip: WS2812B (or a clone), data through ~330 ohm
STRIP_PIN = 15
LED_COUNT = 10
COLOR_ORDER = "GRB"  # check with ./dod hcl pattern: "every LED red" must look red

# the 8x8: a MAX7219 module, on its input side (DIN)
MATRIX_DIN = 21
MATRIX_CLK = 18
MATRIX_CS = 19
# hardware SPI 2 would take GPIO19 as its input (MISO), which is the CS here;
# the MAX7219 never answers, so MISO goes to GPIO39, an input-only pin nothing uses
SPI_ID = 2
SPI_MISO_UNUSED = 39
SPI_BAUD = 1_000_000  # lower this first if the 8x8 shows random pixels
# how the module is mounted: check with ./dod hcl pattern ("row 1 from the top", "column 1 from the left")
MATRIX_MIRROR = False  # columns left <-> right
MATRIX_FLIP = False  # rows top <-> bottom

IDLE_AFTER_MS = 3000  # no frame for this long: the board's own idle animation
BOOT_BUTTON = 0  # held during main.py's first second: stay at the REPL
