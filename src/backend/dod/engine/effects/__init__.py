"""Every effect, by id. PRESETS are the ones phones can pick, in the order the
phone shows them."""

from dod.engine.effects.base import Effect
from dod.engine.effects.idle import Idle
from dod.engine.effects.rainbow import Rainbow
from dod.engine.effects.solid import Solid

EFFECTS: dict[str, type[Effect]] = {e.id: e for e in (Solid, Rainbow, Idle)}
PRESETS: dict[str, type[Effect]] = {k: e for k, e in EFFECTS.items() if e.pickable}
