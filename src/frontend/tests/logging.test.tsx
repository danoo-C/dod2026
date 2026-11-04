// The logging page (plan step 4), through the real route, store and socket,
// with the fake WebSocket standing in for the backend.
import { act, cleanup, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LogLine } from "../src/api/messages";
import { routes } from "../src/routes";
import { FakeWebSocket, install, stateAt, WELCOME, type FakeSession } from "./support/fakes";

const T0 = 1_793_710_000;
const lines = (from: number, n: number): LogLine[] =>
  Array.from({ length: n }, (_, i) => ({ t: T0 + from + i, tag: "rgb-core", level: "INFO", text: `frame ${from + i}` }));

let session: FakeSession;

async function open() {
  window.history.replaceState(null, "", "/internal/logging?key=dev");
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: ["/internal/logging"] })} />);
  await act(() => vi.advanceTimersByTimeAsync(0));
}

/** The backend's side of connecting: welcome, state, you, then the history (backend.md 10). */
function backendSends(history: LogLine[]) {
  act(() => {
    FakeWebSocket.last.accept({ ...WELCOME, role: "logging" });
    FakeWebSocket.last.receive(stateAt(T0));
    FakeWebSocket.last.receive({ type: "you", session: "7f3a", position: null, in_control: false, turn_ends_at: null });
    FakeWebSocket.last.receive({ type: "log", lines: history });
  });
}

const shown = () => screen.queryAllByTestId("line").map((row) => row.textContent?.split(" ").at(-1));

beforeEach(() => {
  vi.useFakeTimers();
  session = install();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("the logging page", () => {
  it("connects as logging with the key", async () => {
    await open();
    expect(session.calls()).toEqual(["/api/session?key=dev"]);
    expect(FakeWebSocket.last.url).toBe("ws://localhost:3000/ws?role=logging");
  });

  it("opens on a full screen: the history first, then new lines below it", async () => {
    await open();
    backendSends(lines(0, 300));
    expect(shown()).toHaveLength(300);
    expect(shown()[0]).toBe("0");
    act(() => FakeWebSocket.last.receive({ type: "log", lines: lines(300, 5) }));
    expect(shown()).toHaveLength(300); // the oldest left at the top
    expect(shown()[0]).toBe("5");
    expect(shown().at(-1)).toBe("304");
  });

  it("is only the terminal and the badge", async () => {
    await open();
    backendSends(lines(0, 3));
    expect(screen.getByRole("region", { name: "Terminál" })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe("Simulovaná doska · 30 fps");
    expect(document.querySelector(".pv")).toBeNull(); // no preview, no hello page
  });

  it("a dead backend shows on the badge and the strip, and the lines stay", async () => {
    await open();
    backendSends(lines(0, 10));
    act(() => FakeWebSocket.last.serverClose(1006));
    expect(screen.getByTestId("offline")).toBeTruthy();
    expect(document.querySelector(".logging-badge .badge.bad")?.textContent).toBe("Server nedostupný");
    expect(shown()).toHaveLength(10);
  });

  it("a reconnect gets the history again: no line twice", async () => {
    await open();
    backendSends(lines(0, 100)); // early in the day: 100 lines so far
    act(() => FakeWebSocket.last.serverClose(1006));
    await act(() => vi.advanceTimersByTimeAsync(5000));
    backendSends(lines(0, 105)); // the same 100, and 5 written while it was away
    expect(shown()).toEqual(Array.from({ length: 105 }, (_, i) => String(i)));
  });

  it("without the key: an error screen, no terminal", async () => {
    await open();
    act(() => FakeWebSocket.last.serverClose(4403));
    expect(screen.getByRole("alert").textContent).toContain("Sem nemáš prístup");
    expect(screen.queryByRole("region", { name: "Terminál" })).toBeNull();
  });
});
