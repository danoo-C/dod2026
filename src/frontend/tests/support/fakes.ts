// A fake WebSocket and /api/session for the connection's tests. The page's
// code uses the globals; install() swaps them for these.
import { vi } from "vitest";

import type { StateMessage, Welcome, You } from "../../src/api/messages";

export class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static all: FakeWebSocket[] = [];

  readyState = FakeWebSocket.CONNECTING;
  sent: unknown[] = [];
  closedByPage: number | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(readonly url: string) {
    FakeWebSocket.all.push(this);
  }

  static get last(): FakeWebSocket {
    const ws = FakeWebSocket.all.at(-1);
    if (ws === undefined) throw new Error("no WebSocket was opened");
    return ws;
  }

  // the page's side
  send(data: string): void {
    if (this.readyState !== FakeWebSocket.OPEN) throw new Error("send() on a socket that isn't open");
    this.sent.push(JSON.parse(data));
  }

  close(code = 1000): void {
    this.closedByPage = code;
    this.readyState = FakeWebSocket.CLOSED;
  }

  // the server's side
  accept(welcome: Welcome = WELCOME): void {
    this.readyState = FakeWebSocket.OPEN;
    this.receive(welcome);
  }

  receive(msg: object): void {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }

  serverClose(code: number): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code });
  }
}

export interface FakeSession {
  fetch: ReturnType<typeof vi.fn>;
  /** URLs of every /api/session call so far */
  calls(): string[];
}

/** Fake WebSocket and fetch. `session` answers /api/session: a status code, or "down" for a network error. */
export function install(session: () => number | "down" = () => 200): FakeSession {
  FakeWebSocket.all = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  const fetch = vi.fn(async (url: string) => {
    const answer = session();
    if (answer === "down") throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify({ session: "7f3a", internal: url.includes("key=") }), { status: answer });
  });
  vi.stubGlobal("fetch", fetch);
  return { fetch, calls: () => fetch.mock.calls.map((c) => String(c[0])) };
}

export function setVisibility(state: "visible" | "hidden"): void {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

// --- messages, as the backend sends them

export const WELCOME: Welcome = {
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
};

export function stateAt(now: number, part: Partial<StateMessage["queue"]> = {}): StateMessage {
  return {
    type: "state",
    now,
    mode: "manual",
    manual: { preset: "rainbow", params: { speed: 0.3 }, matrix: "icon", drawing: "0000000000000000" },
    music: { song: null, title: null, started_at: null, length: null, playing: false, player_connected: false },
    queue: { controller: "7f3a", turn_ends_at: null, turn_over: false, waiting: 0, paused: false, ...part },
    hardware: { state: "connected", simulated: true, fps: 30, error: null },
  };
}

export function you(part: Partial<You> = {}): You {
  return { type: "you", session: "7f3a", position: null, in_control: false, turn_ends_at: null, ...part };
}
