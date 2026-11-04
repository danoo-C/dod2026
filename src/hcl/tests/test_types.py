import dataclasses
import json

import pytest

import hcl
from hcl import (
    MAX_LEDS,
    Connected,
    DeviceInfo,
    DeviceLog,
    Disconnected,
    Frame,
    Incompatible,
    LinkState,
    LinkStatus,
    LogLevel,
    RawText,
)
from hcl import protocol

STRIP = bytes(30)
MATRIX = bytes(8)


# --- Frame ------------------------------------------------------------------


def test_valid_frame():
    f = Frame(strip=bytes(range(30)), matrix=MATRIX, brightness=15)
    assert f.led_count == 10
    assert f.brightness == 15


def test_frame_copies_the_callers_buffer():
    buf = bytearray(30)
    f = Frame(strip=buf, matrix=memoryview(bytes(8)), brightness=0)
    buf[0] = 255
    assert f.strip[0] == 0
    assert type(f.strip) is bytes and type(f.matrix) is bytes


def test_frame_is_immutable():
    f = Frame(strip=STRIP, matrix=MATRIX, brightness=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.brightness = 3


def test_blank_frame():
    f = Frame.blank(10)
    assert f.strip == bytes(30) and f.matrix == bytes(8) and f.brightness == 0


def test_most_leds_that_fit_into_one_message():
    f = Frame(strip=bytes(3 * MAX_LEDS), matrix=MATRIX, brightness=0)
    # the protocol must accept it
    protocol.encode(protocol.FRAME, protocol.frame_payload(0, f.strip, f.matrix, f.brightness))


@pytest.mark.parametrize(
    "kwargs, error",
    [
        (dict(strip=b""), "strip is empty"),
        (dict(strip=bytes(29)), "3 bytes per LED"),
        (dict(strip=bytes(3 * (MAX_LEDS + 1))), "at most"),
        (dict(strip=[0] * 30), "strip must be bytes"),
        (dict(strip="rgb" * 10), "strip must be bytes"),
        (dict(matrix=bytes(7)), "matrix must be 8 bytes"),
        (dict(matrix=bytes(9)), "matrix must be 8 bytes"),
        (dict(brightness=16), "0-15"),
        (dict(brightness=-1), "0-15"),
        (dict(brightness=7.5), "must be an int"),
        (dict(brightness=True), "must be an int"),
    ],
)
def test_frame_rejects(kwargs, error):
    args = dict(strip=STRIP, matrix=MATRIX, brightness=8) | kwargs
    with pytest.raises(ValueError, match=error):
        Frame(**args)


# --- DeviceInfo, LinkState, LinkStatus --------------------------------------


def test_device_info():
    d = DeviceInfo(protocol=1, firmware=(1, 0, 3), led_count=10, color_order="GRB")
    assert d.firmware_str == "1.0.3"
    assert d.simulated is False


def test_link_state_values_are_plain_strings():
    assert [s.value for s in LinkState] == ["disconnected", "connecting", "connected", "incompatible"]
    assert LinkState.CONNECTED == "connected"


def test_status_defaults():
    s = LinkStatus()
    assert s.state is LinkState.DISCONNECTED
    assert s.device is None and s.rtt_ms is None and s.last_error is None
    assert s.frames_sent == s.frames_acked == s.bytes_tx == 0


def test_status_to_dict_is_json_ready():
    device = DeviceInfo(protocol=1, firmware=(1, 0, 3), led_count=10, color_order="GRB", simulated=True)
    s = LinkStatus(state=LinkState.CONNECTED, url="sim", device=device, connected_since=1.5, fps=29.9, rtt_ms=4.2)
    d = s.to_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["state"] == "connected"
    assert d["device"] == {"protocol": 1, "firmware": "1.0.3", "led_count": 10, "color_order": "GRB", "simulated": True}
    assert d["fps"] == 29.9


def test_status_without_device_to_dict():
    assert LinkStatus().to_dict()["device"] is None


# --- LogLevel and events ----------------------------------------------------


def test_log_levels_match_the_protocol():
    assert LogLevel.INFO == protocol.LOG_INFO
    assert LogLevel.WARN == protocol.LOG_WARN
    assert LogLevel.ERROR == protocol.LOG_ERROR


def test_unknown_log_level_counts_as_error():
    assert LogLevel.from_wire(1) is LogLevel.WARN
    assert LogLevel.from_wire(9) is LogLevel.ERROR


def test_events_carry_a_timestamp_and_are_immutable():
    device = DeviceInfo(protocol=1, firmware=(1, 0, 0), led_count=10, color_order="GRB")
    events = [
        Connected(device),
        Connected(device, rebooted=True),
        Disconnected("port closed"),
        DeviceLog(LogLevel.WARN, "matrix glitch"),
        RawText("Traceback (most recent call last):"),
        Incompatible("board speaks protocol 2", protocol=2),
    ]
    for e in events:
        assert e.at > 0
        with pytest.raises(dataclasses.FrozenInstanceError):
            e.at = 0
    assert Connected(device, at=5.0).at == 5.0


# --- the public API ---------------------------------------------------------


def test_public_api_is_exported():
    for name in hcl.__all__:
        assert hasattr(hcl, name), name


def test_internals_are_not_exported():
    exported = set(hcl.__all__)
    assert not exported & {"protocol", "rawtext", "types", "Parser", "LineCollector", "encode"}
    namespace = {}
    exec("from hcl import *", namespace)
    assert set(namespace) - {"__builtins__"} == exported
