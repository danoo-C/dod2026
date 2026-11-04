// Everything a screen shows comes from here (plan step 2, decision 1): the
// server's messages and the connection's status, as one snapshot that
// changes as a whole. React reads it with useStand() (useSyncExternalStore).
//
// The server sends the whole state on every change (backend.md 6), so there
// is nothing to merge: the latest `state`, `you` and `preview` simply win.
import { ServerClock } from "./clock";
import type { Error as ErrorMessage, Incoming, LogLine, Outgoing, Preview, StateMessage, Welcome, You } from "./messages";
import type { Role } from "./roles";
import { StandSocket, type Status } from "./socket";

export const LOG_LINES = 300; // as many as the backend keeps (backend.md 10)
export const TOAST_MS = 3000;

/** What visitors are told when the server refuses something; the rest are bugs, not news. */
const TOASTS: Partial<Record<ErrorMessage["code"], string>> = {
  not_your_turn: "Teraz nie si na rade.",
  no_player: "Hudba sa teraz nedá pustiť: obrazovka stánku nehrá.",
  unknown_song: "Túto skladbu teraz nemáme.",
};

export interface Toast {
  id: number;
  text: string;
}

export interface Snapshot {
  status: Status;
  welcome: Welcome | null;
  state: StateMessage | null;
  you: You | null;
  preview: Preview | null;
  log: readonly LogLine[];
  toast: Toast | null;
}

const EMPTY: Snapshot = {
  status: "connecting",
  welcome: null,
  state: null,
  you: null,
  preview: null,
  log: [],
  toast: null,
};

export class Store {
  readonly clock: ServerClock;
  private snapshot: Snapshot = EMPTY;
  private listeners = new Set<() => void>();
  private toasts = 0;
  private toastTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(clock: ServerClock = new ServerClock()) {
    this.clock = clock;
  }

  // --- for useSyncExternalStore

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly get = (): Snapshot => this.snapshot;

  // --- fed by the socket

  setStatus(status: Status): void {
    this.update({ status });
  }

  apply(msg: Outgoing): void {
    switch (msg.type) {
      case "welcome":
        return this.update({ welcome: msg });
      case "state":
        this.clock.update(msg.now);
        return this.update({ state: msg });
      case "you":
        return this.update({ you: msg });
      case "preview":
        return this.update({ preview: msg });
      case "log": {
        const log = [...this.snapshot.log, ...msg.lines];
        return this.update({ log: log.length > LOG_LINES ? log.slice(-LOG_LINES) : log });
      }
      case "error": {
        const text = TOASTS[msg.code];
        if (text === undefined) {
          if (msg.code !== "rate_limited") console.warn(`dod: the server refused a message: ${msg.code}: ${msg.message}`);
          return; // rate_limited: the controls already send less than the limit
        }
        return this.toast(text);
      }
    }
  }

  // --- toasts

  toast(text: string): void {
    this.toasts += 1;
    this.update({ toast: { id: this.toasts, text } });
    if (this.toastTimer !== null) clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => {
      this.toastTimer = null;
      this.update({ toast: null });
    }, TOAST_MS);
  }

  private update(part: Partial<Snapshot>): void {
    this.snapshot = { ...this.snapshot, ...part };
    for (const listener of [...this.listeners]) listener();
  }
}

/** One screen's connection: the socket feeding its store. */
export class Stand {
  readonly store: Store;
  private readonly socket: StandSocket;

  constructor(readonly role: Role, store: Store = new Store()) {
    this.store = store;
    this.socket = new StandSocket(role, {
      message: (msg) => store.apply(msg),
      status: (status) => store.setStatus(status),
    });
  }

  start(): void {
    this.socket.start();
  }

  stop(): void {
    this.socket.stop();
  }

  // arrow functions: components take them apart (`const { send } = useStandActions()`)

  /** Sends now, or not at all (false while disconnected). */
  readonly send = (msg: Incoming): boolean => this.socket.send(msg);

  readonly takeOver = (): void => this.socket.takeOver();
}
