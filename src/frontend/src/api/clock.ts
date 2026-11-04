// The server's clock (backend.md 6). Phone clocks are often seconds off, so
// every `state` carries the server's `now`, and times like `turn_ends_at`
// are counted down against it, never against the phone's own clock.
//
// A message can only arrive after it was sent, so `server now - local time`
// is never more than the true offset: a late message (a slow phone, a busy
// hotspot) only makes it smaller. The largest of the last few samples is
// the best guess, and a clock that is set while the page runs is followed
// within SAMPLES states.

const SAMPLES = 10;

export class ServerClock {
  private samples: number[] = [];

  constructor(private readonly local: () => number = Date.now) {}

  /** A `state` message's `now` (server seconds) just arrived. */
  update(serverNow: number): void {
    this.samples.push(serverNow * 1000 - this.local());
    if (this.samples.length > SAMPLES) this.samples.shift();
  }

  /** Server time minus local time, in ms; 0 until the first state. */
  get offsetMs(): number {
    return this.samples.length === 0 ? 0 : Math.max(...this.samples);
  }

  /** The server's time now, in seconds. */
  now(): number {
    return (this.local() + this.offsetMs) / 1000;
  }

  /** Whole seconds until a server time (seconds), as a countdown shows them; never below 0. */
  secondsUntil(serverTime: number): number {
    return Math.max(0, Math.ceil(serverTime - this.now()));
  }
}

/** 0:07, 2:59 – how countdowns show seconds. */
export function formatSeconds(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
