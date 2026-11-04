"""Every effect, by id. PRESETS are the ones phones can pick, in the order the
phone shows them."""

from dod.engine.effects.base import Effect
from dod.engine.effects.breathe import Breathe
from dod.engine.effects.comet import Comet
from dod.engine.effects.fire import Fire
from dod.engine.effects.idle import Idle
from dod.engine.effects.music import Music
from dod.engine.effects.police import Police
from dod.engine.effects.rainbow import Rainbow
from dod.engine.effects.solid import Solid
from dod.engine.effects.strobe import Strobe

# the phone's order: the mockup's six, then the plain colour; music and idle can't be picked
EFFECTS: dict[str, type[Effect]] = {
    e.id: e for e in (Rainbow, Fire, Police, Breathe, Comet, Strobe, Solid, Music, Idle)
}
PRESETS: dict[str, type[Effect]] = {k: e for k, e in EFFECTS.items() if e.pickable}
