// The server's clock (backend.md 6; plan step 2).
import { describe, expect, it } from "vitest";

import { formatSeconds, ServerClock } from "../src/api/clock";

const SERVER = 1_793_711_000; // server seconds

function phone(offBySeconds: number) {
  let local = (SERVER - offBySeconds) * 1000; // the phone's ms
  return {
    clock: new ServerClock(() => local),
    pass(ms: number) {
      local += ms;
    },
  };
}

describe("ServerClock", () => {
  it("a phone 30 s behind counts down the server's seconds", () => {
    const { clock, pass } = phone(30);
    clock.update(SERVER);
    expect(clock.offsetMs).toBe(30_000);
    const turnEnds = SERVER + 90; // the server says: 90 s left
    expect(clock.secondsUntil(turnEnds)).toBe(90);
    pass(10_000);
    expect(clock.secondsUntil(turnEnds)).toBe(80);
    pass(85_000);
    expect(clock.secondsUntil(turnEnds)).toBe(0); // never negative
  });

  it("a phone 30 s ahead too", () => {
    const { clock } = phone(-30);
    clock.update(SERVER);
    expect(clock.secondsUntil(SERVER + 90)).toBe(90);
  });

  it("a late message doesn't pull the clock back", () => {
    const { clock, pass } = phone(0);
    clock.update(SERVER);
    pass(2_000);
    clock.update(SERVER); // sent at SERVER, arrived 2 s later (a slow phone)
    expect(clock.offsetMs).toBe(0);
    expect(clock.secondsUntil(SERVER + 60)).toBe(58);
  });

  it("follows a phone clock that is set while the page runs", () => {
    const { clock, pass } = phone(0);
    clock.update(SERVER);
    pass(60_000 + 1000); // the phone's clock jumps a minute ahead
    for (let i = 1; i <= 10; i++) {
      clock.update(SERVER + i);
      pass(1000);
    }
    expect(Math.round(clock.offsetMs / 1000)).toBe(-60);
  });

  it("is the local clock before the first state", () => {
    const { clock } = phone(30);
    expect(clock.offsetMs).toBe(0);
  });
});

describe("formatSeconds", () => {
  it.each([
    [0, "0:00"],
    [7, "0:07"],
    [59.9, "0:59"],
    [179, "2:59"],
    [180, "3:00"],
    [-5, "0:00"],
  ])("%s -> %s", (seconds, text) => expect(formatSeconds(seconds)).toBe(text));
});
