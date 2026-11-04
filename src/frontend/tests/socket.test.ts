// The connection (plan step 2): the session, the close codes, the backoff.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Outgoing } from "../src/api/messages";
import { BACKOFF_MAX_MS, BACKOFF_MIN_MS, StandSocket, type Status } from "../src/api/socket";
import { FakeWebSocket, install, setVisibility, type FakeSession } from "./support/fakes";

let session: FakeSession;
let statuses: Status[];
let messages: Outgoing[];
let sockets: StandSocket[];

function open(role: "phone" | "main" | "logging" = "phone", random?: () => number): StandSocket {
  const socket = new StandSocket(role, { message: (m) => messages.push(m), status: (s) => statuses.push(s) }, random);
  sockets.push(socket);
  socket.start();
  return socket;
}

/** Let the fetch and its promise chain run. */
const settle = () => vi.advanceTimersByTimeAsync(0);

/** How long until the page tries again (a new /api/session call), in ms. */
async function nextTry(limit = 10_000): Promise<number> {
  const before = session.calls().length;
  for (let waited = 0; waited <= limit; waited += 10) {
    if (session.calls().length > before) return waited;
    await vi.advanceTimersByTimeAsync(10);
  }
  throw new Error(`no new try within ${limit} ms`);
}

beforeEach(() => {
  vi.useFakeTimers();
  window.history.replaceState(null, "", "/");
  session = install();
  statuses = [];
  messages = [];
  sockets = [];
});

afterEach(() => {
  for (const s of sockets) s.stop();
  vi.useRealTimers();
});

describe("connecting", () => {
  it("gets the session first, then opens the WebSocket with its role", async () => {
    open("phone");
    expect(session.calls()).toEqual(["/api/session"]);
    expect(FakeWebSocket.all).toHaveLength(0); // not before the cookie is there
    await settle();
    expect(FakeWebSocket.last.url).toBe("ws://localhost:3000/ws?role=phone");
    FakeWebSocket.last.accept();
    expect(statuses).toEqual(["open"]);
    expect(messages.map((m) => m.type)).toEqual(["welcome"]);
  });

  it("passes the internal key once, and takes it out of the address bar", async () => {
    window.history.replaceState(null, "", "/internal/main?key=dev&x=1");
    open("main");
    await settle();
    expect(session.calls()).toEqual(["/api/session?key=dev"]);
    expect(window.location.pathname + window.location.search).toBe("/internal/main?x=1");
    expect(FakeWebSocket.last.url).toBe("ws://localhost:3000/ws?role=main");
    FakeWebSocket.last.serverClose(1006);
    await nextTry();
    expect(session.calls()[1]).toBe("/api/session"); // the cookie has it now
  });

  it("a phone never sends a key, even with one in the address", async () => {
    window.history.replaceState(null, "", "/?key=dev");
    open("phone");
    await settle();
    expect(session.calls()).toEqual(["/api/session"]);
  });

  it("a wrong key is forbidden, and no WebSocket opens", async () => {
    session = install(() => 403);
    window.history.replaceState(null, "", "/internal/main?key=wrong");
    open("main");
    await settle();
    expect(statuses).toEqual(["forbidden"]);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWebSocket.all).toHaveLength(0);
    expect(session.calls()).toHaveLength(1);
  });

  it("a backend that is down is tried again", async () => {
    let answer: number | "down" = "down";
    session = install(() => answer);
    open();
    await settle();
    expect(statuses).toEqual(["offline"]);
    answer = 200;
    const waited = await nextTry();
    expect(waited).toBeGreaterThanOrEqual(BACKOFF_MIN_MS - 10);
    await settle();
    FakeWebSocket.last.accept();
    expect(statuses).toEqual(["offline", "open"]);
  });
});

describe("close codes (backend.md 9)", () => {
  async function connected(role: "phone" | "main" = "phone") {
    const socket = open(role);
    await settle();
    FakeWebSocket.last.accept();
    statuses.length = 0;
    return socket;
  }

  it("4401: /api/session once, at once, then connects again", async () => {
    await connected();
    FakeWebSocket.last.serverClose(4401);
    expect(session.calls()).toHaveLength(2); // right away, no wait
    await settle();
    expect(FakeWebSocket.all).toHaveLength(2);
    // still no cookie: now it backs off instead of hammering the server
    FakeWebSocket.last.serverClose(4401);
    expect(await nextTry()).toBeGreaterThanOrEqual(BACKOFF_MIN_MS - 10);
  });

  it("4403: forbidden, never tries again", async () => {
    await connected();
    FakeWebSocket.last.serverClose(4403);
    expect(statuses).toEqual(["forbidden"]);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWebSocket.all).toHaveLength(1);
    expect(session.calls()).toHaveLength(1);
  });

  it("4400: broken, never tries again", async () => {
    await connected();
    FakeWebSocket.last.serverClose(4400);
    expect(statuses).toEqual(["broken"]);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWebSocket.all).toHaveLength(1);
  });

  it("4001: replaced, waits for takeOver()", async () => {
    const socket = await connected("main");
    FakeWebSocket.last.serverClose(4001);
    expect(statuses).toEqual(["replaced"]);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWebSocket.all).toHaveLength(1);
    socket.takeOver();
    expect(statuses).toEqual(["replaced", "connecting"]);
    expect(FakeWebSocket.all).toHaveLength(2);
    FakeWebSocket.last.accept();
    expect(statuses.at(-1)).toBe("open");
  });

  it("takeOver() does nothing unless replaced", async () => {
    const socket = await connected("main");
    socket.takeOver();
    expect(FakeWebSocket.all).toHaveLength(1);
  });

  it.each([1001, 1006, 1009, 1011])("%i: offline, connects again after the backoff", async (code) => {
    await connected();
    FakeWebSocket.last.serverClose(code);
    expect(statuses).toEqual(["offline"]);
    const waited = await nextTry();
    expect(waited).toBeGreaterThanOrEqual(BACKOFF_MIN_MS - 10);
    expect(waited).toBeLessThanOrEqual(BACKOFF_MAX_MS);
    await settle();
    expect(FakeWebSocket.all).toHaveLength(2);
  });
});

describe("backoff", () => {
  it("doubles from 0.5 s to at most 5 s, and starts over after a welcome", async () => {
    open("phone", () => 0.5); // no jitter
    await settle();
    const waits = [];
    for (let i = 0; i < 6; i++) {
      FakeWebSocket.last.serverClose(1006);
      waits.push(await nextTry());
      await settle();
    }
    expect(waits).toEqual([500, 1000, 2000, 4000, 5000, 5000]);
    FakeWebSocket.last.accept();
    FakeWebSocket.last.serverClose(1006);
    expect(await nextTry()).toBe(500);
  });

  it("stays between 0.5 and 5 s with any jitter", () => {
    for (const r of [0, 0.25, 0.5, 0.75, 0.999]) {
      const socket = new StandSocket("phone", { message() {}, status() {} }, () => r);
      for (let attempts = 1; attempts <= 10; attempts++) {
        Object.assign(socket, { attempts });
        const delay = socket.delay();
        expect(delay).toBeGreaterThanOrEqual(BACKOFF_MIN_MS);
        expect(delay).toBeLessThanOrEqual(BACKOFF_MAX_MS);
      }
    }
  });

  it("a page that becomes visible again tries at once", async () => {
    open();
    await settle();
    FakeWebSocket.last.accept();
    for (let i = 0; i < 4; i++) {
      FakeWebSocket.last.serverClose(1006); // the phone was locked; the waits grow
      await nextTry();
      await settle();
    }
    FakeWebSocket.last.serverClose(1006);
    const before = session.calls().length;
    setVisibility("hidden");
    expect(session.calls()).toHaveLength(before);
    setVisibility("visible");
    expect(session.calls()).toHaveLength(before + 1);
  });
});

describe("sending", () => {
  it("only while connected, and nothing is kept for later", async () => {
    const socket = open();
    expect(socket.send({ type: "join_queue" })).toBe(false); // not yet
    await settle();
    expect(socket.send({ type: "join_queue" })).toBe(false); // not before welcome
    FakeWebSocket.last.accept();
    expect(socket.send({ type: "set_preset", preset: "rainbow" })).toBe(true);
    expect(FakeWebSocket.last.sent).toEqual([{ type: "set_preset", preset: "rainbow" }]);
    FakeWebSocket.last.serverClose(1006);
    expect(socket.send({ type: "set_param", name: "speed", value: 1 })).toBe(false);
    await nextTry();
    await settle();
    FakeWebSocket.last.accept();
    expect(FakeWebSocket.last.sent).toEqual([]); // the value from the gap is gone
  });
});

describe("stopping", () => {
  it("closes the socket and never tries again", async () => {
    const socket = open();
    await settle();
    const ws = FakeWebSocket.last;
    ws.accept();
    socket.stop();
    expect(ws.closedByPage).toBe(1000);
    ws.serverClose(1006); // the browser's close event, after stop()
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWebSocket.all).toHaveLength(1);
    expect(session.calls()).toHaveLength(1);
  });

  it("ignores a message that isn't JSON", async () => {
    open();
    await settle();
    FakeWebSocket.last.accept();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    FakeWebSocket.last.onmessage?.({ data: "not json" });
    expect(messages).toHaveLength(1);
    expect(warn).toHaveBeenCalledOnce();
  });
});
