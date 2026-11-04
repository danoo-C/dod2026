// What a screen shows about its connection, through the real Stand and the
// fake WebSocket (plan step 2).
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useStand, StandProvider } from "../src/api/useStand";
import { ConnectionGate } from "../src/components/Connection";
import { FakeWebSocket, install } from "./support/fakes";

function Child() {
  const waiting = useStand((s) => s.state?.queue.waiting ?? "–");
  return <p>obrazovka ({waiting})</p>;
}

async function show(role: "phone" | "main" = "main") {
  render(
    <StandProvider role={role}>
      <ConnectionGate>
        <Child />
      </ConnectionGate>
    </StandProvider>,
  );
  await act(() => vi.advanceTimersByTimeAsync(0));
  act(() => FakeWebSocket.last.accept());
}

beforeEach(() => {
  vi.useFakeTimers();
  window.history.replaceState(null, "", "/internal/main?key=dev");
  install();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("ConnectionGate", () => {
  it("shows the screen while connected", async () => {
    await show();
    expect(screen.getByText("obrazovka (–)")).toBeTruthy();
    expect(screen.queryByTestId("offline")).toBeNull();
  });

  it("offline: a strip on top, the screen stays, and it comes back by itself", async () => {
    await show();
    act(() => FakeWebSocket.last.serverClose(1006));
    expect(screen.getByTestId("offline").textContent).toBe("Odpojené, pripájam znova…");
    expect(screen.getByText("obrazovka (–)")).toBeTruthy();
    await act(() => vi.advanceTimersByTimeAsync(5000));
    act(() => FakeWebSocket.last.accept());
    expect(screen.queryByTestId("offline")).toBeNull();
  });

  it("replaced: the whole screen, and Prevziať takes over", async () => {
    await show();
    act(() => FakeWebSocket.last.serverClose(4001));
    expect(screen.getByRole("alert").textContent).toContain("Otvorené v inom okne");
    expect(screen.queryByText(/obrazovka \(/)).toBeNull();
    act(() => fireEvent.click(screen.getByRole("button", { name: "Prevziať" })));
    expect(FakeWebSocket.all).toHaveLength(2);
    act(() => FakeWebSocket.last.accept());
    expect(screen.getByText("obrazovka (–)")).toBeTruthy();
  });

  it("forbidden: says how to open it, no screen", async () => {
    await show();
    act(() => FakeWebSocket.last.serverClose(4403));
    expect(screen.getByRole("alert").textContent).toContain("start.bat");
  });

  it("broken: says it is a bug", async () => {
    await show("phone");
    act(() => FakeWebSocket.last.serverClose(4400));
    expect(screen.getByRole("alert").textContent).toContain("chyba v aplikácii");
  });

  it("a component re-renders with the part it reads", async () => {
    await show();
    act(() =>
      FakeWebSocket.last.receive({
        type: "state",
        now: 1,
        mode: "idle",
        manual: { preset: "rainbow", params: {}, matrix: "icon", drawing: "0000000000000000" },
        music: { song: null, title: null, started_at: null, length: null, playing: false, player_connected: true },
        queue: { controller: null, turn_ends_at: null, turn_over: false, waiting: 4, paused: false },
        hardware: { state: "connected", simulated: true, fps: 30, error: null },
      }),
    );
    expect(screen.getByText("obrazovka (4)")).toBeTruthy();
  });
});
