"""Effect, Param and Context: the interface every effect has (docs/backend.md 7.2).

An effect declares its parameters; the phone builds its controls from them
(`describe()`, sent in `welcome`), so a new preset needs no frontend change.
Effects are pure: the same Context gives the same Picture.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from dod.engine.color import HEX
from dod.engine.picture import MATRIX_ROWS, Picture

Kind = Literal["slider", "color", "choice", "toggle"]


@dataclass(frozen=True)
class Audio:
    """The latest spectrum from the main screen (music mode, step 8)."""

    bands: tuple[float, ...]  # 32 bands, low to high, 0-1
    beat: bool = False  # a kick in this spectrum
    # kept by dod.music.audio, so the music effect can stay pure:
    beats: tuple[float, ...] = ()  # seconds since each of the last few kicks, newest first
    count: int = 0  # kicks so far; the light show changes scene every 16
    travel: float = 0.0  # loudness summed over time: grows faster when the music is louder
    bass: float = 0.0  # how much bass the song has lately, 0-1 (smoothed over ~1.5 s)
    bass_travel: float = 0.0  # bass summed over time: the colours drift faster with more bass
    kick_sum: float = 0.0  # the bass at each kick, summed: the colours jump further on bassy kicks
    snares: tuple[float, ...] = ()  # seconds since the last few snares (claps), newest first
    snare_count: int = 0
    hats: tuple[float, ...] = ()  # seconds since the last few hi-hats, newest first
    hat_count: int = 0
    drop: float = math.inf  # seconds since the last drop (a kick with the bass back, in a calm part)
    drop_count: int = 0
    level: float = 0.0  # loudness 0-1, smoothed over ~0.35 s
    calm: float = 0.0  # 0-1: no kicks lately, or the bass gone (a breakdown, a quiet intro)
    build: float = 0.0  # 0-1: a calm part getting louder or busier, towards a drop
    held: tuple[float, ...] = ()  # the bands, rising at once and falling slowly (the 8x8's bars); () = bands


@dataclass(frozen=True)
class Context:
    """Everything an effect may use. `params` is complete and checked: every
    parameter the effect declares is there, with a valid value."""

    led_count: int
    t: float  # seconds since the effect started
    dt: float = 1 / 30  # seconds since the last frame
    params: Mapping[str, Any] = field(default_factory=dict)
    audio: Audio | None = None
    drawing: bytes = bytes(MATRIX_ROWS)


@dataclass(frozen=True)
class Param:
    """One control on the phone. Create them with slider(), color(), choice(), toggle().

    Values: slider -> float, color -> '#rrggbb' (lower case), choice -> one of
    the option values, toggle -> bool. check() turns what a phone sent into that,
    or raises ValueError.
    """

    name: str
    label: str  # Slovak, shown on the phone
    kind: Kind
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: tuple[tuple[str, str], ...] = ()  # (value, label)

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise ValueError(f"parameter name must be an identifier, got {self.name!r}")
        if self.kind == "slider":
            if self.min is None or self.max is None or not self.min < self.max:
                raise ValueError(f"slider {self.name}: needs min < max")
        if self.kind == "choice":
            values = [v for v, _ in self.options]
            if not values or len(set(values)) != len(values):
                raise ValueError(f"choice {self.name}: needs options, each value once")
        object.__setattr__(self, "default", self.check(self.default))

    @classmethod
    def slider(cls, name: str, label: str, min: float, max: float, *, default: float,
               step: float | None = None) -> Param:
        return cls(name, label, "slider", default, min=float(min), max=float(max), step=step)

    @classmethod
    def color(cls, name: str, label: str, *, default: str) -> Param:
        return cls(name, label, "color", default)

    @classmethod
    def choice(cls, name: str, label: str, options: Sequence[tuple[str, str]], *, default: str) -> Param:
        return cls(name, label, "choice", default, options=tuple((str(v), str(l)) for v, l in options))

    @classmethod
    def toggle(cls, name: str, label: str, *, default: bool = False) -> Param:
        return cls(name, label, "toggle", default)

    def check(self, value: Any) -> Any:
        if self.kind == "slider":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{self.name} must be a number, got {value!r}")
            assert self.min is not None and self.max is not None
            if not self.min <= value <= self.max:
                raise ValueError(f"{self.name} must be {self.min:g}-{self.max:g}, got {value!r}")
            return float(value)
        if self.kind == "color":
            if not isinstance(value, str) or not HEX.fullmatch(value):
                raise ValueError(f"{self.name} must be a colour like #ff8000, got {value!r}")
            return value.lower()
        if self.kind == "choice":
            if value not in {v for v, _ in self.options}:
                raise ValueError(f"{self.name} must be one of {', '.join(v for v, _ in self.options)}, got {value!r}")
            return value
        if not isinstance(value, bool):
            raise ValueError(f"{self.name} must be true or false, got {value!r}")
        return value

    def samples(self) -> list[Any]:
        """The values worth trying: the extremes and the default (tests, soak test)."""
        if self.kind == "slider":
            return [self.min, self.max, self.default]
        if self.kind == "color":
            return [self.default, "#000000", "#ffffff"]
        if self.kind == "choice":
            return [v for v, _ in self.options]
        return [False, True]

    def describe(self) -> dict[str, Any]:
        """For the phone (`welcome`)."""
        d: dict[str, Any] = {"name": self.name, "label": self.label, "kind": self.kind, "default": self.default}
        if self.kind == "slider":
            d |= {"min": self.min, "max": self.max, "step": self.step}
        if self.kind == "choice":
            d["options"] = [{"value": v, "label": l} for v, l in self.options]
        return d


class Effect:
    """A preset, or one of the modes phones can't pick (music, idle)."""

    id: ClassVar[str]
    name: ClassVar[str]  # Slovak, shown on the phone
    params: ClassVar[tuple[Param, ...]] = ()
    pickable: ClassVar[bool] = True  # False: phones can't choose it

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for attr in ("id", "name"):
            if not isinstance(cls.__dict__.get(attr), str):
                raise TypeError(f"effect {cls.__name__} needs a class attribute {attr!r}")
        names = [p.name for p in cls.params]
        if len(set(names)) != len(names):
            raise TypeError(f"effect {cls.__name__} declares a parameter twice")

    def render(self, ctx: Context) -> Picture:
        raise NotImplementedError

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return {p.name: p.default for p in cls.params}

    @classmethod
    def check_param(cls, name: str, value: Any) -> Any:
        """A value from a phone, checked; ValueError for an unknown name or a bad value."""
        for p in cls.params:
            if p.name == name:
                return p.check(value)
        raise ValueError(f"{cls.id} has no parameter {name!r}")

    @classmethod
    def describe(cls) -> dict[str, Any]:
        """For the phone (`welcome`)."""
        return {"id": cls.id, "name": cls.name, "params": [p.describe() for p in cls.params]}
