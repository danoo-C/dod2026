// The store (plan step 2): what the screens read.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LogLine } from "../src/api/messages";
import { LOG_LINES, Store, TOAST_MS } from "../src/api/store";
import { stateAt, WELCOME, you } from "./support/fakes";

const line = (i: number): LogLine => ({ t: i, tag: "rgb-core", level: "INFO", text: `frame ${i}` });

let store: Store;

beforeEach(() => {
  vi.useFakeTimers();
  store = new Store();
});

afterEach(() => vi.useRealTimers());

describe("Store", () => {
  it("keeps the latest of each message", () => {
    store.apply(WELCOME);
    store.apply(stateAt(100));
    store.apply(you({ position: 2 }));
    store.apply({ type: "preview", leds: ["#ff0000"], matrix: "0000000000000000", brightness: 8 });
    store.apply(stateAt(101, { waiting: 3 }));
    const s = store.get();
    expect(s.welcome?.session).toBe("7f3a");
    expect(s.state?.queue.waiting).toBe(3);
    expect(s.you?.position).toBe(2);
    expect(s.preview?.brightness).toBe(8);
  });

  it("a new snapshot on every change, the same one otherwise", () => {
    const before = store.get();
    expect(store.get()).toBe(before); // useSyncExternalStore needs this
    store.apply(stateAt(100));
    expect(store.get()).not.toBe(before);
    expect(store.get().welcome).toBe(before.welcome); // untouched parts keep their identity
  });

  it("tells its listeners, and stops when they unsubscribe", () => {
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    store.apply(you());
    store.setStatus("open");
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    store.apply(you());
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("sets the server clock from every state", () => {
    store.apply(stateAt(Date.now() / 1000 + 30));
    expect(Math.round(store.clock.offsetMs / 1000)).toBe(30);
  });

  it("keeps the last 300 log lines", () => {
    store.apply({ type: "log", lines: Array.from({ length: 250 }, (_, i) => line(i)) });
    store.apply({ type: "log", lines: Array.from({ length: 100 }, (_, i) => line(250 + i)) });
    const log = store.get().log;
    expect(log).toHaveLength(LOG_LINES);
    expect(log[0]?.t).toBe(50);
    expect(log.at(-1)?.t).toBe(349);
  });
});

describe("errors from the server", () => {
  it.each([
    ["not_your_turn", "Teraz nie si na rade."],
    ["no_player", "Hudba sa teraz nedá pustiť: obrazovka stánku nehrá."],
    ["unknown_song", "Túto skladbu teraz nemáme."],
  ] as const)("%s becomes a toast in Slovak", (code, text) => {
    store.apply({ type: "error", code, message: "…" });
    expect(store.get().toast?.text).toBe(text);
  });

  it("a toast goes away after a while; a new one starts the time again", () => {
    store.apply({ type: "error", code: "not_your_turn", message: "" });
    vi.advanceTimersByTime(TOAST_MS - 500);
    store.apply({ type: "error", code: "no_player", message: "" });
    vi.advanceTimersByTime(TOAST_MS - 500);
    expect(store.get().toast?.text).toContain("Hudba");
    vi.advanceTimersByTime(500);
    expect(store.get().toast).toBeNull();
  });

  it("rate_limited is ignored; invalid and forbidden are bugs, not news", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    store.apply({ type: "error", code: "rate_limited", message: "" });
    expect(warn).not.toHaveBeenCalled();
    store.apply({ type: "error", code: "invalid", message: "speed: too big" });
    store.apply({ type: "error", code: "forbidden", message: "" });
    expect(store.get().toast).toBeNull();
    expect(warn).toHaveBeenCalledTimes(2);
  });
});
