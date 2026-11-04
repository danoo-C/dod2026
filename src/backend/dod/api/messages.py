"""Every WebSocket message as a Pydantic model (docs/backend.md 9).

Browser -> server messages are parsed with parse(); anything unknown or
malformed raises ValidationError, and the sender gets `error: invalid`.
Server -> browser messages are built from these models too, so their JSON
Schema (dod.api.schema, src/backend/schema/messages.json) is what the
frontend's TypeScript types are generated from.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

Hex16 = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{16}$")]  # 8 rows of the 8x8
SongId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{11}$")]  # a YouTube id
Name = Annotated[str, StringConstraints(min_length=1, max_length=40)]
ParamValue = bool | float | Annotated[str, StringConstraints(max_length=40)]
Band = Annotated[float, Field(ge=0, le=1)]

ROLES = ("phone", "main", "logging")
Role = Literal["phone", "main", "logging"]
ErrorCode = Literal["invalid", "forbidden", "not_your_turn", "no_player", "unknown_song", "rate_limited"]
LogLevel = Literal["DEBUG", "INFO", "OK", "WARN"]  # the fake terminal's colours; real errors never go there


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Out(BaseModel):
    # in the schema, fields with a default (like `type`) are still required: the
    # server always sends them, and the frontend tells messages apart by `type`
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


# --- browser -> server --------------------------------------------------------


class JoinQueue(_In):
    type: Literal["join_queue"]


class LeaveQueue(_In):
    type: Literal["leave_queue"]


class SetPreset(_In):
    type: Literal["set_preset"]
    preset: Name


class SetParam(_In):
    type: Literal["set_param"]
    name: Name
    value: ParamValue


class SetMatrix(_In):
    type: Literal["set_matrix"]
    mode: Literal["icon", "drawing"]
    drawing: Hex16 | None = None  # None keeps the drawing


class PlaySong(_In):
    type: Literal["play_song"]
    song: SongId


class LoadingStarted(_In):
    type: Literal["loading_started"]


class Spectrum(_In):
    type: Literal["spectrum"]
    bands: Annotated[list[Band], Field(min_length=32, max_length=32)]
    beat: bool = False


class Player(_In):
    type: Literal["player"]
    song: SongId
    position: Annotated[float, Field(ge=0)]  # seconds
    ended: bool = False


class Admin(_In):
    type: Literal["admin"]
    action: Literal["skip", "pause_queue", "resume_queue", "stop_song"]


Incoming = Annotated[
    JoinQueue | LeaveQueue | SetPreset | SetParam | SetMatrix | PlaySong | LoadingStarted | Spectrum | Player | Admin,
    Field(discriminator="type"),
]
INCOMING: TypeAdapter[Incoming] = TypeAdapter(Incoming)


def parse(text: str | bytes) -> Incoming:
    """One message from a browser. Raises pydantic.ValidationError."""
    return INCOMING.validate_json(text)


# --- server -> browser --------------------------------------------------------


class OptionInfo(_Out):
    value: str
    label: str


class ParamInfo(_Out):
    name: str
    label: str
    kind: Literal["slider", "color", "choice", "toggle"]
    default: ParamValue
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[OptionInfo] | None = None


class PresetInfo(_Out):
    id: str
    name: str
    params: list[ParamInfo]


class SongInfo(_Out):
    id: str
    title: str
    length: float | None  # seconds, once downloaded
    ready: bool  # downloaded: the main screen can play it


class WifiInfo(_Out):
    ssid: str
    password: str


class Welcome(_Out):
    type: Literal["welcome"] = "welcome"
    role: Role
    session: str | None  # the short public id, as shown in the logs
    presets: list[PresetInfo]
    songs: list[SongInfo]
    public_url: str
    turn_seconds: float
    inactive_seconds: float
    wifi: WifiInfo | None = None  # the hotspot, for its QR code: the main screen's welcome only


class ManualPart(_Out):
    preset: str
    params: dict[str, ParamValue]
    matrix: Literal["icon", "drawing"]
    drawing: str


class MusicPart(_Out):
    song: str | None
    title: str | None
    started_at: float | None
    length: float | None
    playing: bool
    player_connected: bool


class QueuePart(_Out):
    controller: str | None
    turn_ends_at: float | None
    turn_over: bool
    waiting: int
    paused: bool


class HardwarePart(_Out):
    state: str
    simulated: bool
    fps: float
    error: str | None


class StateMessage(_Out):
    type: Literal["state"] = "state"
    now: float
    mode: Literal["manual", "music", "idle"]
    manual: ManualPart
    music: MusicPart
    queue: QueuePart
    hardware: HardwarePart


class You(_Out):
    type: Literal["you"] = "you"
    session: str | None
    position: int | None  # 0 = in control, 1 = next, None = not in the queue
    in_control: bool
    turn_ends_at: float | None


class Preview(_Out):
    type: Literal["preview"] = "preview"
    leds: list[str]  # "#rrggbb", as a person sees them (before gamma)
    matrix: str  # 8 rows as 16 hex characters, like the drawing
    brightness: int  # 0-15


class LogLine(_Out):
    """One line of the fake terminal (docs/backend.md 10); the page does the colours."""

    t: float  # wall clock, seconds
    tag: str  # the made-up subsystem: rgb-core, photon-bus, esp32, …
    level: LogLevel
    text: str


class Log(_Out):
    type: Literal["log"] = "log"
    lines: list[LogLine]


class Error(_Out):
    type: Literal["error"] = "error"
    code: ErrorCode
    message: str


Outgoing = Annotated[Welcome | StateMessage | You | Preview | Log | Error, Field(discriminator="type")]
OUTGOING: TypeAdapter[Outgoing] = TypeAdapter(Outgoing)
