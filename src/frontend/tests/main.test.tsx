// The main screen (plan step 6), through the real route, store and socket,
// with the fake WebSocket as the backend.
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StateMessage, Welcome } from "../src/api/messages";
import { isAdminShortcut } from "../src/components/AdminPanel";
import { routes } from "../src/routes";
import { FakeWebSocket, install, stateAt, WELCOME, you, type FakeSession } from "./support/fakes";

const NOW = Date.now() / 1000;
const WIFI = { ssid: "DOD-SPSE", password: "svetlo2026" };
const MAIN: Welcome = { ...WELCOME, role: "main", session: "main", wifi: WIFI };

let session: FakeSession;

function show(path = "/internal/main") {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
}

async function start(welcome: Welcome = MAIN, state: StateMessage = stateAt(NOW)) {
  window.history.replaceState(null, "", "/internal/main?key=dev");
  show();
  fireEvent.click(screen.getByRole("button", { name: "Spustiť" }));
  await act(() => vi.advanceTimersByTimeAsync(0));
  act(() => {
    FakeWebSocket.last.accept(welcome);
    FakeWebSocket.last.receive(state);
    FakeWebSocket.last.receive(you({ session: "main" }));
  });
}

function music(part: Partial<StateMessage["music"]> = {}): StateMessage {
  const s = stateAt(NOW, { controller: "7f3a", waiting: 2 });
  return {
    ...s,
    mode: "music",
    music: { song: "dQw4w9WgXcQ", title: "Never Gonna Give You Up", started_at: NOW - 102, length: 210, playing: true, player_connected: true, ...part },
  };
}

const ctrlAltD = () => fireEvent.keyDown(window, { code: "KeyD", key: "d", ctrlKey: true, altKey: true });
const sent = () => FakeWebSocket.last.sent;
const qrLabels = () => [...document.querySelectorAll(".qr figcaption")].map((c) => c.textContent);

beforeEach(() => {
  vi.useFakeTimers({ now: NOW * 1000 });
  window.localStorage.clear();
  session = install();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Spustiť", () => {
  it("starts the audio in the click itself, where the browser allows sound", () => {
    const resume = vi.fn(async () => {});
    class FakeAudioContext {
      sampleRate = 48000;
      resume = resume;
    }
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.spyOn(console, "warn").mockImplementation(() => {}); // later songs in this file get no graph from the fake
    window.history.replaceState(null, "", "/internal/main?key=dev");
    show();
    expect(resume).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Spustiť" }));
    expect(resume).toHaveBeenCalledOnce();
  });

  it("the main screen connects only after the click: until then it isn't the player", async () => {
    window.history.replaceState(null, "", "/internal/main?key=dev");
    show();
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(FakeWebSocket.all).toHaveLength(0);
    expect(session.calls()).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Spustiť" }));
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(session.calls()).toEqual(["/api/session?key=dev"]);
    expect(FakeWebSocket.last.url).toBe("ws://localhost:3000/ws?role=main");
  });
});

describe("the right part", () => {
  it("no song: the big QR codes, the queue and the large preview", async () => {
    await start(MAIN, stateAt(NOW, { controller: "7f3a", waiting: 3 }));
    expect(screen.getByTestId("attract")).toBeTruthy();
    expect(screen.getByTestId("video").hidden).toBe(true); // in the page (the <video> stays), hidden
    expect(screen.getByText("Naskenuj kód a ovládaj svetlá")).toBeTruthy();
    expect(screen.getByText("V rade čaká 3 ľudia.")).toBeTruthy();
    expect(qrLabels()).toEqual(["1. Wi-Fi", "2. Stránka"]); // big ones only: the bar has none
    expect(document.querySelector(".pv.large")).not.toBeNull();
  });

  it("a song: the video, and the bar gets the small QR codes", async () => {
    await start(MAIN, music());
    expect(screen.getByTestId("video").textContent).toContain("Never Gonna Give You Up");
    expect(screen.getByTestId("video").hidden).toBe(false);
    expect(screen.queryByTestId("attract")).toBeNull();
    expect(qrLabels()).toEqual(["1. Wi-Fi", "2. Stránka"]);
    expect(document.querySelector(".bar .qrs")).not.toBeNull();
  });

  it("switches with the mode, both ways", async () => {
    await start(MAIN, music());
    act(() => FakeWebSocket.last.receive(stateAt(NOW)));
    expect(screen.getByTestId("attract")).toBeTruthy();
    act(() => FakeWebSocket.last.receive(music()));
    expect(screen.getByTestId("video").hidden).toBe(false);
  });

  it("without the Wi-Fi settings: only the page's QR code", async () => {
    await start({ ...MAIN, wifi: null });
    expect(qrLabels()).toEqual(["Stránka"]);
    expect(screen.getByText("Otvor stránku v mobile a postav sa do radu.")).toBeTruthy();
  });

  it("the QR codes hold the page's address and the hotspot", async () => {
    await start();
    const titles = [...document.querySelectorAll(".qr svg title")].map((t) => t.textContent);
    expect(titles).toEqual(["1. Wi-Fi", "2. Stránka"]);
    // the SVG is drawn from the value; the label is what the test can read, the value is checked in components.test
  });
});

describe("the info bar", () => {
  it("a song: its title and how far it is", async () => {
    await start(MAIN, music());
    expect(within(document.querySelector(".bar") as HTMLElement).getByText("Never Gonna Give You Up")).toBeTruthy();
    expect(screen.getByTestId("song-time").textContent).toBe("1:42 / 3:30");
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(screen.getByTestId("song-time").textContent).toBe("1:52 / 3:30");
  });

  it("manual: the preset; the queue length; the badge", async () => {
    await start(MAIN, stateAt(NOW, { waiting: 4 }));
    const bar = document.querySelector(".bar") as HTMLElement;
    expect(within(bar).getByText("Preset: Dúha")).toBeTruthy();
    expect(bar.querySelector(".q .big")?.textContent).toBe("4");
    expect(within(bar).getByRole("status").textContent).toBe("Simulovaná doska · 30 fps");
  });
});

describe("the admin panel", () => {
  it("isn't in the page until Ctrl+Alt+D, and Esc closes it", async () => {
    await start();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText("Preskočiť toho, kto ovláda")).toBeNull();
    ctrlAltD();
    expect(screen.getByRole("dialog", { name: "Správa stánku" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("each action sends what it says", async () => {
    await start(MAIN, music());
    ctrlAltD();
    fireEvent.click(screen.getByRole("button", { name: "Preskočiť toho, kto ovláda" }));
    fireEvent.click(screen.getByRole("button", { name: "Pozastaviť rad" }));
    fireEvent.click(screen.getByRole("button", { name: "Zastaviť skladbu" }));
    expect(sent()).toEqual([
      { type: "admin", action: "skip" },
      { type: "admin", action: "pause_queue" },
      { type: "admin", action: "stop_song" },
    ]);
    // the state says paused: the button resumes
    act(() => FakeWebSocket.last.receive({ ...music(), queue: { ...music().queue, paused: true } }));
    fireEvent.click(screen.getByRole("button", { name: "Spustiť rad" }));
    expect(sent().at(-1)).toEqual({ type: "admin", action: "resume_queue" });
  });

  it("nothing to skip or stop: those are greyed out", async () => {
    await start(MAIN, stateAt(NOW, { controller: null }));
    ctrlAltD();
    expect((screen.getByRole("button", { name: "Preskočiť toho, kto ovláda" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Zastaviť skladbu" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("the terminal's width, 25-33 %, remembered", async () => {
    await start();
    const nb = document.querySelector(".nb") as HTMLElement;
    expect(nb.style.getPropertyValue("--term-w")).toBe("30%");
    ctrlAltD();
    fireEvent.change(screen.getByLabelText(/Šírka terminálu/), { target: { value: "33" } });
    expect(nb.style.getPropertyValue("--term-w")).toBe("33%");
    expect(window.localStorage.getItem("dod.termWidth")).toBe("33");
    cleanup();
    await start();
    expect((document.querySelector(".nb") as HTMLElement).style.getPropertyValue("--term-w")).toBe("33%");
  });

  it("the board's status in full, from /api/status", async () => {
    await start();
    const base = globalThis.fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url === "/api/status"
          ? new Response(
              JSON.stringify({
                link: { state: "connected", url: "sim", fps: 30, rtt_ms: 4.2, frames_sent: 1234, reconnects: 0, last_error: null, device: { firmware: "0.0.0" } },
                render: { fps: 30, led_count: 10 },
                tasks: { running: ["render loop", "hub"], restarts: { "render loop": 0 } },
                connections: 3,
              }),
            )
          : base(url),
      ),
    );
    ctrlAltD();
    await act(() => vi.advanceTimersByTimeAsync(0));
    const status = screen.getByLabelText("Stav");
    expect(within(status).getByText("Odoslané snímky").nextSibling?.textContent).toBe("1234");
    expect(within(status).getByText("Úlohy").nextSibling?.textContent).toBe("render loop, hub");
    expect(within(status).getByText("Posledná chyba").nextSibling?.textContent).toBe("–");
  });

  it("Ctrl+Alt+D does nothing on the phone", async () => {
    show("/");
    await act(() => vi.advanceTimersByTimeAsync(0));
    act(() => FakeWebSocket.last.accept());
    ctrlAltD();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("the shortcut is Ctrl+Alt+D only, by the key's position", () => {
    const key = (init: KeyboardEventInit) => new KeyboardEvent("keydown", init);
    expect(isAdminShortcut(key({ code: "KeyD", ctrlKey: true, altKey: true }))).toBe(true);
    expect(isAdminShortcut(key({ code: "KeyD", key: "Đ", ctrlKey: true, altKey: true }))).toBe(true); // Slovak AltGr
    expect(isAdminShortcut(key({ code: "KeyD", ctrlKey: true }))).toBe(false);
    expect(isAdminShortcut(key({ code: "KeyD", ctrlKey: true, altKey: true, shiftKey: true }))).toBe(false);
    expect(isAdminShortcut(key({ code: "KeyF", ctrlKey: true, altKey: true }))).toBe(false);
  });
});

describe("a newer main screen", () => {
  it("replaced: Otvorené v inom okne, and Prevziať takes over", async () => {
    await start();
    act(() => FakeWebSocket.last.serverClose(4001));
    expect(screen.getByRole("alert").textContent).toContain("Otvorené v inom okne");
    fireEvent.click(screen.getByRole("button", { name: "Prevziať" }));
    expect(FakeWebSocket.all).toHaveLength(2);
  });
});
