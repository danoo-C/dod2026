// The connection to the backend (backend.md 9; plan step 2).
//
//   GET /api/session[?key=…]  the session cookie (and, with the key, the internal one)
//   WS  /ws?role=…            everything live; the browser sends both cookies
//
// What a close code means, and what the page does:
//
//   4401  no session cookie          /api/session again, then connect
//   4403  main/logging without key   "forbidden": stop, show an error
//   4400  bad role in the URL        "broken": stop, a bug
//   4001  a newer main screen        "replaced": stop until takeOver()
//   1009, 1001, anything else        "offline": connect again with backoff
//
// Backoff: 0.5 s, doubling, at most 5 s, with up to 20 % jitter; it starts
// over once the server says `welcome`. A page that becomes visible again
// (a phone that was locked: iOS closes its WebSockets) connects at once.
//
// Nothing is queued while disconnected: send() returns false, and a slider
// value from before the gap is worse than none.
import type { Incoming, Outgoing } from "./messages";
import type { Role } from "./roles";

export type Status =
  | "connecting" // the first time, or after takeOver()
  | "open" // welcome received
  | "offline" // lost; trying again
  | "replaced" // 4001: another main screen took over
  | "forbidden" // 4403, or a wrong key: the internal pages need the key
  | "broken"; // 4400: the page asked for a role that doesn't exist (a bug)

export const CLOSE = {
  replaced: 4001,
  badRole: 4400,
  noSession: 4401,
  noKey: 4403,
} as const;

export const BACKOFF_MIN_MS = 500;
export const BACKOFF_MAX_MS = 5000;
const JITTER = 0.2;

export interface SocketEvents {
  message(msg: Outgoing): void;
  status(status: Status): void;
}

export class StandSocket {
  private ws: WebSocket | null = null;
  private status: Status = "connecting";
  private attempts = 0; // failures since the last welcome
  private retry: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private key: string | null;

  constructor(
    readonly role: Role,
    private readonly on: SocketEvents,
    private readonly random: () => number = Math.random,
  ) {
    // the internal pages are opened with ?key=…; it goes to /api/session once
    this.key = role === "phone" ? null : new URLSearchParams(window.location.search).get("key");
  }

  start(): void {
    this.stopped = false;
    document.addEventListener("visibilitychange", this.onVisible);
    window.addEventListener("online", this.onVisible);
    void this.session();
  }

  stop(): void {
    this.stopped = true;
    this.clearRetry();
    document.removeEventListener("visibilitychange", this.onVisible);
    window.removeEventListener("online", this.onVisible);
    const ws = this.ws;
    this.ws = null;
    ws?.close(1000);
  }

  /** After 4001: this window becomes the main screen again (the other one gets 4001). */
  takeOver(): void {
    if (this.status !== "replaced" || this.stopped) return;
    this.attempts = 0;
    this.setStatus("connecting");
    this.connect();
  }

  /** Sends now, or not at all: false while not connected. */
  send(msg: Incoming): boolean {
    if (this.ws === null || this.status !== "open" || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(msg));
    return true;
  }

  get current(): Status {
    return this.status;
  }

  // --- the session, then the WebSocket

  private async session(): Promise<void> {
    const url = this.key === null ? "/api/session" : `/api/session?key=${encodeURIComponent(this.key)}`;
    let response: Response;
    try {
      response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
    } catch {
      return this.lost(); // the backend is down: try again later
    }
    if (this.stopped) return;
    if (response.status === 403) return this.end("forbidden");
    if (!response.ok) return this.lost();
    if (this.key !== null) {
      // the cookie holds it now; out of the address bar, so it isn't shared or bookmarked
      this.key = null;
      const clean = new URL(window.location.href);
      clean.searchParams.delete("key");
      window.history.replaceState(window.history.state, "", clean);
    }
    this.connect();
  }

  private connect(): void {
    this.clearRetry();
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${window.location.host}/ws?role=${this.role}`);
    this.ws = ws;
    ws.onmessage = (event) => {
      if (this.ws !== ws) return;
      let msg: Outgoing;
      try {
        msg = JSON.parse(String(event.data)) as Outgoing;
      } catch {
        console.warn("dod: a message that isn't JSON", event.data);
        return;
      }
      if (msg.type === "welcome") {
        this.attempts = 0;
        this.setStatus("open");
      }
      this.on.message(msg);
    };
    ws.onclose = (event) => {
      if (this.ws !== ws) return; // an old socket, already replaced
      this.ws = null;
      this.closed(event.code);
    };
  }

  private closed(code: number): void {
    if (this.stopped) return;
    switch (code) {
      case CLOSE.noSession:
        if (this.attempts === 0) {
          // the cookie is simply missing (cleared, expired): fetch it now;
          // only if that happens again does it go through the backoff
          this.attempts = 1;
          void this.session();
          return;
        }
        return this.lost();
      case CLOSE.noKey:
        return this.end("forbidden");
      case CLOSE.badRole:
        return this.end("broken");
      case CLOSE.replaced:
        return this.end("replaced");
      default:
        return this.lost();
    }
  }

  // --- trying again

  /** Lost, or never got there: try again after the backoff. Every try starts
   * with /api/session (cheap), so a backend that restarted is fine too. */
  private lost(): void {
    if (this.stopped) return;
    this.attempts += 1;
    this.setStatus("offline");
    this.clearRetry();
    this.retry = setTimeout(() => {
      this.retry = null;
      void this.session();
    }, this.delay());
  }

  /** The wait before the next try, in ms: 0.5 s doubling, at most 5 s, ±20 %, never outside 0.5–5 s. */
  delay(): number {
    const base = Math.min(BACKOFF_MAX_MS, BACKOFF_MIN_MS * 2 ** Math.max(0, this.attempts - 1));
    const jittered = base * (1 + (this.random() * 2 - 1) * JITTER);
    return Math.round(Math.min(BACKOFF_MAX_MS, Math.max(BACKOFF_MIN_MS, jittered)));
  }

  private readonly onVisible = (): void => {
    if (document.visibilityState !== "visible" || this.stopped || this.retry === null) return;
    this.clearRetry(); // waiting for a retry: try now instead
    void this.session();
  };

  private end(status: Status): void {
    this.clearRetry();
    this.setStatus(status);
  }

  private clearRetry(): void {
    if (this.retry !== null) clearTimeout(this.retry);
    this.retry = null;
  }

  private setStatus(status: Status): void {
    if (status === this.status) return;
    this.status = status;
    this.on.status(status);
  }
}
