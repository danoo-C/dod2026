import random

from hcl.rawtext import LineCollector


def test_lines_from_text():
    lc = LineCollector()
    lines = lc.feed(b"MicroPython v1.29.0 on 2026-09-30; Generic ESP32 module\r\nType \"help()\" for more\n")
    assert lines == ['MicroPython v1.29.0 on 2026-09-30; Generic ESP32 module', 'Type "help()" for more']


def test_traceback_split_over_several_reads():
    lc = LineCollector()
    lines = lc.feed(b"Traceback (most recent call last):\r\n  File \"main.py\", li")
    lines += lc.feed(b"ne 42, in <module>\r\nOSError: [Errno 19] ENODEV\r\n")
    assert lines == [
        "Traceback (most recent call last):",
        'File "main.py", line 42, in <module>',
        "OSError: [Errno 19] ENODEV",
    ]


def test_binary_noise_is_dropped():
    rng = random.Random(1)
    noise = bytes(rng.randrange(256) for _ in range(2000)).replace(b"\n", b"")
    lc = LineCollector()
    assert lc.feed(noise + b"\n") == []


def test_control_characters_are_noise():
    lc = LineCollector()
    assert lc.feed(b"\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\n") == []


def test_empty_lines_are_skipped():
    lc = LineCollector()
    assert lc.feed(b"\r\n\n  \nok\n") == ["ok"]


def test_unfinished_line_waits_until_flush():
    lc = LineCollector()
    assert lc.feed(b">>> ") == []
    assert lc.flush() == [">>>"]
    assert lc.flush() == []


def test_long_line_without_newline_is_cut():
    lc = LineCollector(max_line=50)
    lines = lc.feed(b"a" * 120)
    assert lines == ["a" * 50, "a" * 50]
    assert lc.flush() == ["a" * 20]


def test_utf8_text():
    lc = LineCollector()
    assert lc.feed("teplota 23 °C\n".encode()) == ["teplota 23 °C"]
