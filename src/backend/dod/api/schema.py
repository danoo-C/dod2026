"""The JSON Schema of every WebSocket message, for the frontend's TypeScript
types (docs/backend.md 9). Regenerate with `./dod schema`; a test fails when
the file is out of date."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from dod.api.messages import INCOMING, OUTGOING

FILE = Path(__file__).resolve().parents[2] / "schema" / "messages.json"


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


def main() -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(build(), encoding="utf-8")
    print(f"wrote {FILE}")


if __name__ == "__main__":
    main()
