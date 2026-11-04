// The WebSocket messages' TypeScript types, from the backend's JSON Schema
// (backend.md 9; plan step 1, decision 4).
//
//   node scripts/types.mjs          write src/api/messages.ts
//   node scripts/types.mjs --check  fail if it is out of date (part of npm test)
//
// ./dod schema runs both halves: the Pydantic models -> messages.json, then this.
import { readFile, writeFile } from "node:fs/promises";

import { compile } from "json-schema-to-typescript";

const SCHEMA = new URL("../../backend/schema/messages.json", import.meta.url);
const OUT = new URL("../src/api/messages.ts", import.meta.url);

const BANNER = `/* Generated from src/backend/schema/messages.json by scripts/types.mjs.
 * Do not edit: change the models in src/backend/dod/api/messages.py and run ./dod schema. */`;

// Pydantic titles every field ("Type", "Name", ...), which would become one
// alias type per field (Type1, Type2, ...). Only the models keep their names.
// minItems/maxItems would turn the 32 bands into a 32-element tuple; the
// server checks the length anyway.
function simplify(node, isModel = false) {
  if (Array.isArray(node)) return node.map((n) => simplify(n));
  if (node === null || typeof node !== "object") return node;
  const out = {};
  for (const [key, value] of Object.entries(node)) {
    if ((key === "title" && !isModel) || key === "minItems" || key === "maxItems") continue;
    if (key === "$defs") {
      out.$defs = Object.fromEntries(Object.entries(value).map(([name, def]) => [name, simplify(def, true)]));
    } else {
      out[key] = simplify(value);
    }
  }
  return out;
}

async function build() {
  const schema = simplify(JSON.parse(await readFile(SCHEMA, "utf8")));
  schema.title = "Messages"; // the root type's name
  const ts = await compile(schema, "Messages", {
    bannerComment: BANNER,
    additionalProperties: false, // the server refuses unknown fields
    unreachableDefinitions: true,
    format: true,
  });
  return (
    ts +
    `
/** Browser -> server. */
export type Incoming = Messages["incoming"];
/** Server -> browser. */
export type Outgoing = Messages["outgoing"];
`
  );
}

const ts = await build();
if (process.argv.includes("--check")) {
  const current = await readFile(OUT, "utf8").catch(() => "");
  if (current !== ts) {
    console.error("src/api/messages.ts is out of date: run ./dod schema");
    process.exit(1);
  }
} else {
  await writeFile(OUT, ts);
  console.log("wrote src/frontend/src/api/messages.ts");
}
