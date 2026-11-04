// The shared components (plan step 3).
import { act, cleanup, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LogLine } from "../src/api/messages";
import { Stand } from "../src/api/store";
import { StandProvider } from "../src/api/useStand";
import { Badge, badgeFor } from "../src/components/Badge";
import { Countdown } from "../src/components/Countdown";
import { LoadingScreen, MAX_MS, MIN_MS, STEPS } from "../src/components/LoadingScreen";
import { decodeMatrix, Matrix, matrixLevel, Preview, Strip } from "../src/components/Preview";
import { Qr, wifiQr } from "../src/components/Qr";
import { tagColour, Terminal, timestamp } from "../src/components/Terminal";
import { install, stateAt } from "./support/fakes";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

// --- Preview ------------------------------------------------------------------

describe("the 8x8", () => {
  const HEART = "183c7effff7e3c18"; // a diamond: 00011000, 00111100, 01111110, 11111111, ...
  const rows = (pixels: boolean[]) =>
    Array.from({ length: 8 }, (_, y) => pixels.slice(y * 8, y * 8 + 8).map((on) => (on ? "#" : ".")).join(""));

  it("decodes 16 hex characters into rows, bit 7 on the left", () => {
    expect(rows(decodeMatrix(HEART))).toEqual([
      "...##...",
      "..####..",
      ".######.",
      "########",
      "########",
      ".######.",
      "..####..",
      "...##...",
    ]);
    expect(rows(decodeMatrix("8001000000000000")).slice(0, 2)).toEqual(["#.......", ".......#"]);
  });

  it("shows nothing for anything malformed", () => {
    for (const bad of ["", "183c", "zz3c7effff7e3c18", "183c7effff7e3c1800"]) {
      expect(decodeMatrix(bad).some(Boolean)).toBe(false);
    }
  });

  it("draws the pixels that are on, dimmed by the brightness", () => {
    const { container, rerender } = render(<Matrix hex={HEART} brightness={15} />);
    expect(container.querySelectorAll(".px")).toHaveLength(64);
    expect(container.querySelectorAll(".px.on")).toHaveLength(2 + 4 + 6 + 8 + 8 + 6 + 4 + 2);
    const level = () => screen.getByTestId("matrix").style.getPropertyValue("--level");
    expect(level()).toBe("1");
    rerender(<Matrix hex={HEART} brightness={3} />);
    expect(level()).toBe("0.2");
    rerender(<Matrix hex={HEART} brightness={0} />);
    expect(level()).toBe("0");
    expect(matrixLevel(99)).toBe(1);
  });
});

describe("the strip", () => {
  it("one LED per colour; black ones look off", () => {
    render(<Strip leds={["#ff0000", "#000000", "#050505", "#38d4ff"]} />);
    const leds = screen.getAllByTestId("led");
    expect(leds).toHaveLength(4);
    expect(leds[0]?.style.background).toBe("rgb(255, 0, 0)");
    expect(leds[1]?.getAttribute("style")).toBeNull();
    expect(leds[2]?.getAttribute("style")).toBeNull(); // too dark to see
    expect(leds[3]?.style.boxShadow).toContain("0.75");
  });

  it("before the first preview: 10 LEDs, all off, an empty 8x8", () => {
    const { container } = render(<Preview preview={null} />);
    expect(screen.getAllByTestId("led")).toHaveLength(10);
    expect(container.querySelectorAll(".px.on")).toHaveLength(0);
  });
});

// --- Terminal -----------------------------------------------------------------

const line = (i: number, part: Partial<LogLine> = {}): LogLine & { id: number } => ({
  id: i,
  t: 1_793_710_972.481,
  tag: "rgb-core",
  level: "INFO",
  text: `frame ${i}`,
  ...part,
});

describe("Terminal", () => {
  it("keeps the last 300 of 1000 lines, newest at the bottom", () => {
    render(<Terminal lines={Array.from({ length: 1000 }, (_, i) => line(i))} />);
    const rows = screen.getAllByTestId("line");
    expect(rows).toHaveLength(300);
    expect(rows[0]?.textContent).toContain("frame 700");
    expect(rows.at(-1)?.textContent).toContain("frame 999");
  });

  it("colours every level and every tag", () => {
    const { container } = render(
      <Terminal lines={(["DEBUG", "INFO", "OK", "WARN"] as const).map((level, i) => line(i, { level, tag: `tag${i}` }))} />,
    );
    for (const level of ["DEBUG", "INFO", "OK", "WARN"]) {
      expect(container.querySelector(`.lv-${level}`)?.textContent?.trim()).toBe(level);
    }
    for (const tag of container.querySelectorAll(".tg")) {
      expect(tag.className).toMatch(/tg-(hot|warm|cool|ok|vio)$/);
    }
  });

  it("the same tag always gets the same colour", () => {
    expect(tagColour("rgb-core")).toBe(tagColour("rgb-core"));
    const colours = new Set(["rgb-core", "photon-bus", "lattice", "serial", "queue", "esp32", "fft", "thermal"].map(tagColour));
    expect(colours.size).toBeGreaterThan(2);
  });

  it("shows board text as text, never as HTML", () => {
    const { container } = render(<Terminal lines={[line(1, { text: '<b>bold</b><img src=x onerror="alert(1)">' })]} />);
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByTestId("line").textContent).toContain("<b>bold</b>");
  });

  it("lines up time, tag and level like a terminal", () => {
    render(<Terminal lines={[line(1, { tag: "fft", level: "OK", text: "32 bins ok" })]} />);
    expect(screen.getByTestId("line").textContent).toMatch(/^\[\d\d:\d\d:\d\d\.481\] fft {8}OK {4}32 bins ok$/);
    expect(timestamp(0.007)).toMatch(/\.007\]$/);
  });

  it("starts with the banner and ends with the cursor", () => {
    const { container } = render(<Terminal lines={[]} />);
    expect(container.querySelector(".banner")?.textContent).toContain("LIGHT ENGINE v4.2.0");
    expect(container.querySelector(".cur")).not.toBeNull();
  });
});

// --- LoadingScreen ------------------------------------------------------------

describe("LoadingScreen", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    install();
  });

  async function runUntilDone(random: () => number) {
    const onDone = vi.fn();
    const stand = new Stand("phone");
    const send = vi.spyOn(stand, "send");
    render(
      <StrictMode>
        <StandProvider role="phone" stand={stand}>
          <LoadingScreen onDone={onDone} random={random} />
        </StandProvider>
      </StrictMode>,
    );
    let elapsed = 0;
    while (onDone.mock.calls.length === 0 && elapsed < 10_000) {
      await act(() => vi.advanceTimersByTimeAsync(10));
      elapsed += 10;
    }
    return { onDone, send, elapsed };
  }

  it.each([
    ["the shortest", () => 0],
    ["a middle one", () => 0.5],
    ["the longest", () => 0.9999],
  ])("%s ends within 2-4 s, and sends loading_started once", async (_, random) => {
    const { onDone, send, elapsed } = await runUntilDone(random);
    expect(onDone).toHaveBeenCalledOnce();
    expect(elapsed).toBeGreaterThanOrEqual(MIN_MS);
    expect(elapsed).toBeLessThanOrEqual(MAX_MS);
    expect(send.mock.calls).toEqual([[{ type: "loading_started" }]]); // once, even in StrictMode
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(onDone).toHaveBeenCalledOnce();
  });

  it("ticks the steps off and reaches 100 %", async () => {
    render(<LoadingScreen durationMs={2000} />);
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("0");
    await act(() => vi.advanceTimersByTimeAsync(1000));
    const half = Number(screen.getByRole("progressbar").getAttribute("aria-valuenow"));
    expect(half).toBeGreaterThan(30);
    expect(half).toBeLessThan(100);
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("100");
    expect(document.querySelectorAll(".steps .done")).toHaveLength(STEPS.length);
  });
});

// --- Qr -----------------------------------------------------------------------

describe("Qr", () => {
  it("draws the code with its label", () => {
    const { container } = render(<Qr value="http://192.168.137.1:8000" label="2. Stránka" />);
    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.querySelectorAll("svg path").length).toBeGreaterThan(0);
    expect(container.querySelector("figcaption")?.textContent).toBe("2. Stránka");
    expect(container.querySelector("svg title")?.textContent).toBe("2. Stránka"); // for screen readers
  });

  it("joins a Wi-Fi, with the special characters escaped", () => {
    expect(wifiQr("DOD-SPSE", "svetlo2026")).toBe("WIFI:S:DOD-SPSE;T:WPA;P:svetlo2026;;");
    expect(wifiQr('a;b,c:d"e\\f', "p;w")).toBe('WIFI:S:a\\;b\\,c\\:d\\"e\\\\f;T:WPA;P:p\\;w;;');
  });
});

// --- Countdown ----------------------------------------------------------------

describe("Countdown", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    install();
  });

  it("counts down the server's seconds on a phone 30 s off", async () => {
    const stand = new Stand("phone");
    const serverNow = Date.now() / 1000 + 30; // the phone is 30 s behind
    stand.store.apply(stateAt(serverNow));
    render(
      <StandProvider role="phone" stand={stand}>
        <Countdown to={serverNow + 90} total={180} />
      </StandProvider>,
    );
    expect(screen.getByTestId("countdown").textContent).toBe("1:30");
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(screen.getByTestId("countdown").textContent).toBe("1:20");
    await act(() => vi.advanceTimersByTimeAsync(120_000));
    expect(screen.getByTestId("countdown").textContent).toBe("0:00");
  });

  it("dashes without a time", () => {
    render(<Countdown to={null} />);
    expect(screen.getByTestId("countdown").textContent).toBe("–:––");
  });
});

// --- Badge --------------------------------------------------------------------

describe("Badge", () => {
  const hw = (state: string, extra: object = {}) => ({ state, simulated: false, fps: 29.9, error: null, ...extra });

  it.each([
    ["open", hw("connected"), "ok", "Doska pripojená · 30 fps"],
    ["open", hw("connected", { simulated: true }), "warn", "Simulovaná doska · 30 fps"],
    ["open", hw("connecting"), "warn", "Pripájam dosku…"],
    ["open", hw("disconnected", { error: "read timeout" }), "bad", "Doska odpojená"],
    ["open", hw("incompatible"), "bad", "Nekompatibilná doska"],
    ["connecting", null, "warn", "Pripájam sa k serveru…"],
    ["offline", hw("connected"), "bad", "Server nedostupný"],
    ["open", null, "warn", "Čakám na stav…"],
  ] as const)("%s + %o: %s, %s", (status, hardware, tone, text) => {
    expect(badgeFor(status, hardware)).toMatchObject({ tone, text });
  });

  it("the board's error on hover", () => {
    render(<Badge status="open" hardware={hw("disconnected", { error: "read timeout" })} />);
    expect(screen.getByRole("status").getAttribute("title")).toBe("read timeout");
    expect(screen.getByRole("status").dataset.tone).toBe("bad");
  });
});
