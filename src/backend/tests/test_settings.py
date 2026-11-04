"""Settings from the environment (docs/backend.md 11)."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from dod.main import create_app
from dod.settings import Settings, SettingsError

DOCS = Path("/work/docs/backend.md")


def problems(env):
    with pytest.raises(SettingsError) as e:
        Settings.from_env(env)
    return e.value.problems


# --- defaults -----------------------------------------------------------------


def test_defaults_without_any_variable():
    s = Settings.from_env({})
    assert s.serial == "sim"
    assert s.baud == 115200
    assert s.led_count == 10
    assert s.power_limit_ma == 1500
    assert s.brightness == 0.8
    assert s.turn_seconds == 180
    assert s.inactive_seconds == 30
    assert s.idle_seconds == 30
    assert s.audio_delay_ms == 0
    assert s.public_url == "http://localhost:8000"
    assert s.cache_dir == Path("/work/cache")
    assert s.log_level == "INFO"
    assert s.wifi_ssid is None and s.wifi_password is None


def test_the_internal_key_is_random_when_not_set():
    a, b = Settings.from_env({}).internal_key, Settings.from_env({}).internal_key
    assert a != b and len(a) >= 16


def test_other_variables_are_ignored():
    assert Settings.from_env({"PATH": "/bin", "ESP_PORT": "/dev/ttyUSB1", "DODGE": "x"}).serial == "sim"


def test_the_table_in_the_docs_matches():
    # every row of backend.md 11 is a setting with that default, and every setting has a row
    section = DOCS.read_text(encoding="utf-8").split("## 11. Settings", 1)[1].split("\n## ", 1)[0]
    rows = dict(re.findall(r"^\| `(DOD_[A-Z_]+)` \| ([^|]+?) \|", section, re.MULTILINE))
    fields = {Settings.env_name(f): f for f in Settings.model_fields}
    assert set(rows) == set(fields)
    defaults = Settings.from_env({})
    for var, doc in rows.items():
        if var == "DOD_INTERNAL_KEY":
            assert doc.startswith("random")
            continue
        value = getattr(defaults, fields[var])
        if value is None:
            assert doc == "–", var  # not set
            continue
        doc = doc.strip("`")
        if isinstance(value, (int, float)):
            assert float(doc) == value, var
        else:
            assert doc == str(value), var


# --- good values --------------------------------------------------------------


def test_values_are_parsed():
    s = Settings.from_env({
        "DOD_SERIAL": "socket://host.docker.internal:7777",
        "DOD_BAUD": "921600",
        "DOD_LED_COUNT": "60",
        "DOD_BRIGHTNESS": " 0.25 ",
        "DOD_TURN_SECONDS": "90.5",
        "DOD_AUDIO_DELAY_MS": "180",
        "DOD_INTERNAL_KEY": "k3y",
        "DOD_PUBLIC_URL": "http://192.168.137.1:8000/",
        "DOD_CACHE_DIR": "/tmp/songs",
        "DOD_LOG_LEVEL": "debug",
    })
    assert s.serial == "socket://host.docker.internal:7777"
    assert (s.baud, s.led_count, s.brightness, s.turn_seconds, s.audio_delay_ms) == (921600, 60, 0.25, 90.5, 180)
    assert s.internal_key == "k3y"
    assert s.public_url == "http://192.168.137.1:8000"  # trailing slash dropped
    assert s.cache_dir == Path("/tmp/songs")
    assert s.log_level == "DEBUG"


@pytest.mark.parametrize("url", ["sim", "sim?latency_ms=8&drop=0.02", "/dev/ttyUSB0", "/dev/ttyACM1",
                                 "socket://localhost:7777"])
def test_serial_urls_accepted(url):
    assert Settings.from_env({"DOD_SERIAL": url}).serial == url


def test_settings_are_read_only():
    s = Settings()
    with pytest.raises(Exception):
        s.brightness = 0.1  # type: ignore[misc]


# --- wrong values -------------------------------------------------------------


@pytest.mark.parametrize("var, value, says", [
    ("DOD_BRIGHTNESS", "-0.1", "greater than or equal to 0"),
    ("DOD_BRIGHTNESS", "1.5", "less than or equal to 1"),
    ("DOD_BRIGHTNESS", "bright", "valid number"),
    ("DOD_BRIGHTNESS", "nan", "finite number"),
    ("DOD_TURN_SECONDS", "inf", "finite number"),
    ("DOD_TURN_SECONDS", "0", "greater than 0"),
    ("DOD_INACTIVE_SECONDS", "-5", "greater than 0"),
    ("DOD_IDLE_SECONDS", "", "valid number"),
    ("DOD_LED_COUNT", "0", "greater than or equal to 1"),
    ("DOD_LED_COUNT", "10.5", "valid integer"),
    ("DOD_BAUD", "fast", "valid integer"),
    ("DOD_POWER_LIMIT_MA", "0", "greater than 0"),
    ("DOD_AUDIO_DELAY_MS", "5000", "less than or equal to 2000"),
    ("DOD_SERIAL", "", "expected sim"),
    ("DOD_SERIAL", "ttyUSB0", "expected sim"),
    ("DOD_SERIAL", "socket://host", "expected sim"),
    ("DOD_SERIAL", "COM3", "Windows COM port"),
    ("DOD_PUBLIC_URL", "192.168.137.1:8000", "expected an address"),
    ("DOD_PUBLIC_URL", "ftp://192.168.137.1", "expected an address"),
    ("DOD_PUBLIC_URL", "http://192.168.137.1:8000/phone", "only scheme, host and port"),
    ("DOD_INTERNAL_KEY", "", "at least 1 character"),
    ("DOD_CACHE_DIR", "", "expected a directory"),
    ("DOD_LOG_LEVEL", "LOUD", "expected one of DEBUG, INFO, WARNING, ERROR"),
])
def test_wrong_values_name_the_variable(var, value, says):
    [problem] = problems({var: value})
    assert problem.startswith(f"{var}={value!r}: ")
    assert says in problem


def test_the_wifi_is_both_or_neither():
    s = Settings.from_env({"DOD_WIFI_SSID": "DOD-SPSE", "DOD_WIFI_PASSWORD": "svetlo2026"})
    assert (s.wifi_ssid, s.wifi_password) == ("DOD-SPSE", "svetlo2026")
    for alone in ({"DOD_WIFI_SSID": "DOD-SPSE"}, {"DOD_WIFI_PASSWORD": "svetlo2026"}):
        assert problems(alone) == ["DOD_WIFI_SSID and DOD_WIFI_PASSWORD: set both, or neither"]


@pytest.mark.parametrize("var, value, says", [
    ("DOD_WIFI_PASSWORD", "short", "at least 8 characters"),  # a WPA2 password is 8-63
    ("DOD_WIFI_PASSWORD", "x" * 64, "at most 63 characters"),
    ("DOD_WIFI_SSID", "x" * 33, "at most 32 characters"),
])
def test_wrong_wifi_values_name_the_variable(var, value, says):
    other = {"DOD_WIFI_SSID": "DOD-SPSE", "DOD_WIFI_PASSWORD": "svetlo2026"}
    found = problems({**other, var: value})
    assert any(p.startswith(f"{var}={value!r}: ") and says in p for p in found), found


def test_unknown_variables_are_an_error_with_a_hint():
    [problem] = problems({"DOD_BRIGHTNES": "0.5"})
    assert problem == "DOD_BRIGHTNES: unknown setting, did you mean DOD_BRIGHTNESS?"
    [problem] = problems({"DOD_WHATEVER": "1"})
    assert problem == "DOD_WHATEVER: unknown setting"


def test_every_problem_is_reported_at_once():
    found = problems({"DOD_BRIGHTNESS": "2", "DOD_LED_COUNT": "-1", "DOD_TYPO": "x"})
    # unknown variables first, then the settings in the order of backend.md 11
    assert [p.split(":")[0].split("=")[0] for p in found] == ["DOD_TYPO", "DOD_LED_COUNT", "DOD_BRIGHTNESS"]
    message = str(SettingsError(found))
    assert message.startswith("bad settings:\n  ")


# --- the app ------------------------------------------------------------------


def test_the_app_keeps_its_settings():
    s = Settings(brightness=0.3)
    assert create_app(s).state.settings is s


def test_a_wrong_setting_stops_the_backend_with_a_message():
    # the real start: uvicorn's factory, in its own process
    result = subprocess.run(
        [sys.executable, "-c", "from dod.main import create_app; create_app()"],
        env={"DOD_BRIGHTNESS": "2", "DOD_SERIAL": "COM3", "PATH": "/usr/local/bin:/usr/bin"},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "dod: bad settings:" in result.stderr
    assert "DOD_BRIGHTNESS='2'" in result.stderr and "DOD_SERIAL='COM3'" in result.stderr
