"""The JSON Schema of every WebSocket message, for the frontend's TypeScript
types (docs/backend.md 9), and the presets as `welcome` describes them, for
the frontend's tests (the phone builds its controls from them). Regenerate
with `./dod schema`; a test fails when either file is out of date."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from dod.api.messages import INCOMING, OUTGOING, PresetInfo
from dod.engine.effects import PRESETS

FILE = Path(__file__).resolve().parents[2] / "schema" / "messages.json"
PRESETS_FILE = FILE.with_name("presets.json")


def build() -> str:
    """Incoming messages as the server accepts them, outgoing ones as it sends
    them (every field present), in one document with shared definitions."""
    keys, defs = TypeAdapter.json_schemas([("incoming", "validation", INCOMING),
                                           ("outgoing", "serialization", OUTGOING)])
    schema = {
        "title": "DOD 2026 WebSocket messages",
        "description": "incoming: browser -> server, outgoing: server -> browser (docs/backend.md 9)",
        "type": "object",
        "properties": {
            "incoming": keys[("incoming", "validation")],
            "outgoing": keys[("outgoing", "serialization")],
        },
        "required": ["incoming", "outgoing"],
        **defs,
    }
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def build_presets() -> str:
    """`welcome.presets`, exactly as the hub sends it."""
    presets = [PresetInfo.model_validate(e.describe()).model_dump(mode="json") for e in PRESETS.values()]
    return json.dumps(presets, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    for path, text in ((FILE, build()), (PRESETS_FILE, build_presets())):
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
