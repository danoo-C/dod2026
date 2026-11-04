// The small helpers under the phone (plan step 5).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { decodeMatrix, EMPTY, encodeMatrix, withPixel } from "../src/lib/matrix";
import { decimal, minutes, people } from "../src/lib/slovak";
import { throttle } from "../src/lib/throttle";

describe("throttle", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("a dragged slider: at most 10 a second, and the last value always goes", async () => {
    const sent: number[] = [];
    const t = throttle((v: number) => sent.push(v), 100);
    for (let i = 1; i <= 60; i++) {
      // 60 changes a second, as a finger dragging
      t.push(i);
      await vi.advanceTimersByTimeAsync(1000 / 60);
    }
    expect(sent.length).toBeLessThanOrEqual(11); // the first at once, then one per 100 ms
    expect(sent.length).toBeGreaterThanOrEqual(9);
    await vi.advanceTimersByTimeAsync(100);
    expect(sent.at(-1)).toBe(60); // nothing flushed it, and still the last value went
    for (let i = 1; i < sent.length; i++) expect(sent[i]).toBeGreaterThan(sent[i - 1] ?? 0);
  });

  it("the first value goes at once", () => {
    const send = vi.fn();
    throttle(send, 100).push("a");
    expect(send).toHaveBeenCalledWith("a");
  });

  it("flush sends the waiting value now; nothing waiting, nothing sent", () => {
    const send = vi.fn();
    const t = throttle(send, 100);
    t.push(1);
    t.push(2);
    expect(send.mock.calls).toEqual([[1]]);
    t.flush();
    expect(send.mock.calls).toEqual([[1], [2]]);
    t.flush();
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("cancel drops the waiting value", async () => {
    const send = vi.fn();
    const t = throttle(send, 100);
    t.push(1);
    t.push(2);
    t.cancel();
    await vi.advanceTimersByTimeAsync(500);
    expect(send.mock.calls).toEqual([[1]]);
  });
});

describe("the 8x8 drawing", () => {
  it("round-trips through its 16 hex characters", () => {
    for (const hex of ["183c7effff7e3c18", "8001000000000000", EMPTY, "ffffffffffffffff", "0f0f0f0fa5a55a5a"]) {
      expect(encodeMatrix(decodeMatrix(hex))).toBe(hex);
    }
    expect(encodeMatrix(decodeMatrix("183C7EFFFF7E3C18"))).toBe("183c7effff7e3c18"); // always lower case
  });

  it("one pixel at a time: row 0 on top, bit 7 on the left", () => {
    expect(withPixel(EMPTY, 0, true)).toBe("8000000000000000");
    expect(withPixel(EMPTY, 7, true)).toBe("0100000000000000");
    expect(withPixel(EMPTY, 63, true)).toBe("0000000000000001");
    expect(withPixel("8000000000000000", 0, false)).toBe(EMPTY);
  });
});

describe("Slovak", () => {
  it.each([
    [1, "1 minútu"],
    [2, "2 minúty"],
    [4, "4 minúty"],
    [5, "5 minút"],
    [12, "12 minút"],
    [0, "0 minút"],
  ])("minutes(%i) = %s", (n, text) => expect(minutes(n)).toBe(text));

  it.each([
    [0, "nikto"],
    [1, "1 človek"],
    [3, "3 ľudia"],
    [7, "7 ľudí"],
  ])("people(%i) = %s", (n, text) => expect(people(n)).toBe(text));

  it("numbers have a decimal comma, as many decimals as the step", () => {
    expect(decimal(1.5, 0.5)).toBe("1,5");
    expect(decimal(0.25, 0.05)).toBe("0,25");
    expect(decimal(3, 0.5)).toBe("3");
    expect(decimal(0.3333, null)).toBe("0,33");
  });
});
