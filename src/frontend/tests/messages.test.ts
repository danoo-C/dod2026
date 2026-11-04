// The generated message types (plan step 1, decision 4). Most of this test is
// the type check itself: `npm test` runs tsc first, so a field renamed in
// dod/api/messages.py (and ./dod schema run) breaks these fixtures.
import { describe, expect, it } from "vitest";

import type { Incoming, LogLine, Outgoing, Welcome } from "../src/api/messages";

const welcome: Welcome = {
  type: "welcome",
  role: "phone",
  session: "7f3a",
  presets: [
    {
      id: "rainbow",
      name: "Dúha",
      params: [{ name: "speed", label: "Rýchlosť", kind: "slider", default: 0.3, min: 0.05, max: 2, step: 0.05, options: null }],
    },
  ],
  songs: [],
  public_url: "http://192.168.137.1:8000",
  turn_seconds: 180,
  inactive_seconds: 30,
  wifi: null,
};

const sent: Incoming[] = [
  { type: "join_queue" },
  { type: "set_preset", preset: "rainbow" },
  { type: "set_param", name: "speed", value: 1.5 },
  { type: "set_matrix", mode: "drawing", drawing: "183c7effff7e3c18" },
  { type: "spectrum", bands: Array(32).fill(0.5), beat: true },
];

// the type tells the messages apart: in each branch only that message's fields exist
function describeMessage(msg: Outgoing): string {
  switch (msg.type) {
    case "welcome":
      return `welcome as ${msg.role}`;
    case "log":
      return `${msg.lines.length} lines`;
    case "error":
      return msg.code;
    default:
      return msg.type;
  }
}

describe("message types", () => {
  it("tell outgoing messages apart by type", () => {
    const line: LogLine = { t: 1, tag: "rgb-core", level: "OK", text: "ready" };
    expect(describeMessage(welcome)).toBe("welcome as phone");
    expect(describeMessage({ type: "log", lines: [line] })).toBe("1 lines");
    expect(describeMessage({ type: "error", code: "not_your_turn", message: "wait" })).toBe("not_your_turn");
  });

  it("cover the incoming messages", () => {
    expect(sent.map((m) => m.type)).toEqual(["join_queue", "set_preset", "set_param", "set_matrix", "spectrum"]);
  });
});
