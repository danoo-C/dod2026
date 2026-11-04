"""Settings from environment variables, read once at startup (docs/backend.md 11).

Every setting is `DOD_` + its name in capitals: `brightness` is
`DOD_BRIGHTNESS`. A wrong value, or an unknown `DOD_` variable (a typo would
otherwise silently use the default), raises SettingsError, which names every
bad variable at once.

`DOD_SERIAL` gets a quick check of its form here; whether a `sim?…` option
exists is checked by the HCL when the link is opened (step 4), because only
`dod/hardware.py` may import `hcl`.
"""

from __future__ import annotations

import difflib
import os
import re
import secrets
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

PREFIX = "DOD_"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
SOCKET_URL = re.compile(r"socket://[^:/?#\s]+:\d{1,5}")
COM_PORT = re.compile(r"COM\d+", re.IGNORECASE)


class SettingsError(ValueError):
    """One or more settings are wrong. `problems` has one line per variable."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("bad settings:\n" + "\n".join(f"  {p}" for p in problems))


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

    serial: str = "sim"
    baud: int = Field(115200, gt=0)
    # used until the board says how many LEDs it has; the HCL's upper limit is checked in step 4
    led_count: int = Field(10, ge=1)
    power_limit_ma: int = Field(1500, gt=0)
    brightness: float = Field(0.8, ge=0, le=1)
    turn_seconds: float = Field(180, gt=0)
    inactive_seconds: float = Field(30, gt=0)
    idle_seconds: float = Field(30, gt=0)
    # a Bluetooth speaker adds ~150-250 ms; 2 s is far more than any speaker needs
    audio_delay_ms: int = Field(0, ge=0, le=2000)
    internal_key: str = Field(default_factory=lambda: secrets.token_urlsafe(16), min_length=1)
    public_url: str = "http://localhost:8000"
    cache_dir: Path = Path("/work/cache")
    log_level: str = "INFO"

    @field_validator("serial")
    @classmethod
    def _serial(cls, v: str) -> str:
        if v == "sim" or v.startswith("sim?") or v.startswith("/dev/") or SOCKET_URL.fullmatch(v):
            return v
        if COM_PORT.fullmatch(v):
            raise ValueError("a Windows COM port can't be opened from the container; "
                             "use the bridge, socket://host.docker.internal:7777 (tech-spec 6.2)")
        raise ValueError("expected sim, sim?option=value, /dev/ttyUSB0 or socket://host:port")

    @field_validator("public_url")
    @classmethod
    def _public_url(cls, v: str) -> str:
        parts = urlsplit(v)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("expected an address like http://192.168.137.1:8000")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ValueError("expected only scheme, host and port, like http://192.168.137.1:8000")
        return v.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def _log_level(cls, v: str) -> str:
        if v.upper() not in LOG_LEVELS:
            raise ValueError(f"expected one of {', '.join(LOG_LEVELS)}")
        return v.upper()

    @field_validator("cache_dir")
    @classmethod
    def _cache_dir(cls, v: Path) -> Path:
        if str(v) in ("", "."):
            raise ValueError("expected a directory")
        return v

    @classmethod
    def env_name(cls, field: str) -> str:
        return PREFIX + field.upper()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """The settings from `environ` (default: the process's environment)."""
        environ = os.environ if environ is None else environ
        names = {cls.env_name(f): f for f in cls.model_fields}
        problems = []
        for var in sorted(v for v in environ if v.startswith(PREFIX) and v not in names):
            close = difflib.get_close_matches(var, names, n=1)
            hint = f", did you mean {close[0]}?" if close else ""
            problems.append(f"{var}: unknown setting{hint}")
        values = {field: environ[var] for var, field in names.items() if var in environ}
        try:
            settings = cls(**values)
        except ValidationError as e:
            for err in e.errors():
                field = str(err["loc"][0])
                msg = err["msg"].removeprefix("Value error, ")
                problems.append(f"{cls.env_name(field)}={values.get(field, '')!r}: {msg}")
            settings = None
        if problems:
            raise SettingsError(problems)
        assert settings is not None
        return settings
