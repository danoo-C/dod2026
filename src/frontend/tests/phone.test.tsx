// The phone (plan step 5): which screen it shows for which `you` and state,
// and what it sends – through the real route, store and socket, with the
// fake WebSocket as the backend.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PRESETS from "../../backend/schema/presets.json";
import { ServerClock } from "../src/api/clock";
import type { PresetInfo, QueuePart, StateMessage, You } from "../src/api/messages";
import { routes } from "../src/routes";
import { phoneScreen, waitSeconds } from "../src/screens/phoneScreen";
import { FakeWebSocket, install, stateAt, WELCOME, you } from "./support/fakes";

const NOW = Date.now() / 1000;
const welcome = { ...WELCOME, presets: PRESETS as PresetInfo[] };

async function open() {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: ["/"] })} />);
  await act(() => vi.advanceTimersByTimeAsync(0));
  act(() => FakeWebSocket.last.accept(welcome));
}

function server(state: StateMessage, me: You) {
  act(() => {
    FakeWebSocket.last.receive(state);
    FakeWebSocket.last.receive(me);
  });
}

const sent = () => FakeWebSocket.last.sent as { type: string }[];
const button = (name: string | RegExp) => screen.getByRole("button", { name });

beforeEach(() => {
  vi.useFakeTimers({ now: NOW * 1000 });
  window.history.replaceState(null, "", "/");
  install();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("phoneScreen", () => {
  it.each([
    [null, false, false, "connecting"],
    [you({ position: null }), false, false, "welcome"],
    [you({ position: null }), true, false, "ended"],
    [you({ position: 1 }), false, false, "waiting"],
    [you({ position: 3 }), true, false, "waiting"],
    [you({ position: 0, in_control: true }), true, true, "loading"],
    [you({ position: 0, in_control: true }), true, false, "control"],
  ] as const)("%o, turn seen %s, loading %s: %s", (me, seen, loading, screen) => {
    expect(phoneScreen(me, seen, loading)).toBe(screen);
  });
});

describe("waitSeconds", () => {
  const clock = new ServerClock(() => NOW * 1000);
  const queue = (part: Partial<QueuePart>): QueuePart => ({
    controller: "7f3a",
    turn_ends_at: NOW + 100,
    turn_over: false,
    waiting: 3,
    paused: false,
    ...part,
  });

  it("the rest of the current turn, and a full turn for everyone ahead", () => {
    expect(waitSeconds(1, queue({}), 180, clock)).toBe(100);
    expect(waitSeconds(3, queue({}), 180, clock)).toBe(100 + 2 * 180);
  });

  it("no wait for the current turn when it is over or nobody plays", () => {
    expect(waitSeconds(1, queue({ turn_over: true }), 180, clock)).toBe(0);
    expect(waitSeconds(2, queue({ controller: null, turn_ends_at: null }), 180, clock)).toBe(180);
  });
});

describe("the phone", () => {
  it("not in the queue: what this is, and a button to join", async () => {
    await open();
    server(stateAt(NOW, { controller: "b210", waiting: 2 }), you());
    expect(screen.getByText("Ovládaj svetlá na stánku")).toBeTruthy();
    expect(screen.getByText(/čaká 2 ľudia/)).toBeTruthy();
    fireEvent.click(button("Postaviť sa do radu"));
    expect(sent()).toEqual([{ type: "join_queue" }]);
  });

  it("waiting: the position, about how long, the queue line, and leaving", async () => {
    await open();
    server(stateAt(NOW, { controller: "b210", turn_ends_at: NOW + 100, waiting: 3 }), you({ position: 2 }));
    expect(screen.getByText("2.")).toBeTruthy();
    expect(screen.getByTestId("wait").textContent).toBe("Na rade si približne o 5 minút"); // 100 s + 180 s
    expect(screen.getByLabelText("Rad: si 2. z 3").textContent).toBe("hrá teraz·ty·");
    expect(screen.queryByText("b210")).toBeNull(); // nobody's id
    fireEvent.click(button("Odísť z radu"));
    expect(sent()).toEqual([{ type: "leave_queue" }]);
  });

  it("waiting while the queue is paused says so", async () => {
    await open();
    server(stateAt(NOW, { paused: true, waiting: 1 }), you({ position: 1 }));
    expect(screen.getByTestId("wait").textContent).toBe("Rad je na chvíľu pozastavený");
  });

  it("getting control: the loading screen first, then the controls", async () => {
    await open();
    server(stateAt(NOW, { waiting: 1 }), you({ position: 1 }));
    server(stateAt(NOW, { controller: "7f3a", turn_ends_at: NOW + 180 }), you({ position: 0, in_control: true, turn_ends_at: NOW + 180 }));
    expect(screen.getByRole("progressbar")).toBeTruthy();
    expect(sent()).toEqual([{ type: "loading_started" }]); // the terminal bursts with it
    await act(() => vi.advanceTimersByTimeAsync(4000));
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.getByText("Tvoj ťah!")).toBeTruthy();
    expect(screen.getByTestId("countdown").textContent).toMatch(/^2:5\d$/);
  });

  it("a reload in the middle of a turn goes straight to the controls", async () => {
    await open();
    server(stateAt(NOW, { controller: "7f3a", turn_ends_at: NOW + 60 }), you({ position: 0, in_control: true, turn_ends_at: NOW + 60 }));
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.getByTestId("countdown").textContent).toBe("1:00");
  });

  it("in control: presets, parameters and the drawing send what they should", async () => {
    await open();
    server(stateAt(NOW, { controller: "7f3a", turn_ends_at: NOW + 180 }), you({ position: 0, in_control: true, turn_ends_at: NOW + 180 }));
    fireEvent.click(button("Farba"));
    expect(sent().at(-1)).toEqual({ type: "set_preset", preset: "solid" });
    // the controls are the state's preset's: rainbow until the state says otherwise
    expect(screen.getByText("Nastavenia · Dúha")).toBeTruthy();
    fireEvent.click(button("Doľava"));
    expect(sent().at(-1)).toEqual({ type: "set_param", name: "direction", value: "left" });
    fireEvent.pointerDown(button("riadok 1, stĺpec 1"), { pointerId: 1 });
    fireEvent.pointerUp(button("riadok 1, stĺpec 1"), { pointerId: 1 });
    expect(sent().at(-1)).toEqual({ type: "set_matrix", mode: "drawing", drawing: "8000000000000000" });
    fireEvent.click(button("Ikona presetu"));
    expect(sent().at(-1)).toEqual({ type: "set_matrix", mode: "icon" });
  });

  it("the time is up but nobody waits: the turn goes on", async () => {
    await open();
    server(stateAt(NOW, { controller: "7f3a", turn_ends_at: NOW - 5, turn_over: true, waiting: 0 }), you({ position: 0, in_control: true, turn_ends_at: NOW - 5 }));
    expect(screen.getByText("Kým niekto nepríde")).toBeTruthy();
    expect(screen.getByTestId("countdown").textContent).toBe("∞");
  });

  it("a song: picked on the Hudba tab, with the loading screen", async () => {
    await open();
    act(() =>
      FakeWebSocket.last.receive({ ...welcome, songs: [{ id: "dQw4w9WgXcQ", title: "Never Gonna", length: 213, ready: true }] }),
    );
    const state = stateAt(NOW, { controller: "7f3a", turn_ends_at: NOW + 180 });
    server({ ...state, music: { ...state.music, player_connected: true } }, you({ position: 0, in_control: true, turn_ends_at: NOW + 180 }));
    fireEvent.click(screen.getByRole("tab", { name: "Hudba" }));
    fireEvent.click(button(/Never Gonna/));
    expect(sent().slice(-2)).toEqual([{ type: "play_song", song: "dQw4w9WgXcQ" }, { type: "loading_started" }]);
    expect(screen.getByRole("progressbar")).toBeTruthy();
    await act(() => vi.advanceTimersByTimeAsync(4000));
    expect(screen.getByRole("tab", { name: "Hudba" })).toBeTruthy();
  });

  it("the turn ends: Tvoj čas skončil, and queueing again", async () => {
    await open();
    server(stateAt(NOW, { controller: "7f3a", turn_ends_at: NOW + 1 }), you({ position: 0, in_control: true, turn_ends_at: NOW + 1 }));
    server(stateAt(NOW + 2, { controller: "b210", waiting: 0 }), you({ position: null }));
    expect(screen.getByText("Tvoj čas skončil")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Farba" })).toBeNull(); // no controls any more
    fireEvent.click(button("Znova do radu"));
    expect(sent().at(-1)).toEqual({ type: "join_queue" });
    server(stateAt(NOW + 3, { controller: "b210", waiting: 1 }), you({ position: 1 }));
    expect(screen.getByText("1.")).toBeTruthy();
  });

  it("a phone that isn't in control never shows controls, even after a reload mid-turn", async () => {
    await open();
    server(stateAt(NOW, { controller: "b210", turn_ends_at: NOW + 100, waiting: 1 }), you({ position: 1 }));
    expect(screen.queryByRole("tab", { name: "Hudba" })).toBeNull();
    expect(screen.queryByRole("grid")).toBeNull();
  });

  it("the server's refusal shows as a toast", async () => {
    await open();
    server(stateAt(NOW), you({ position: 1 }));
    act(() => FakeWebSocket.last.receive({ type: "error", code: "not_your_turn", message: "wait" }));
    expect(screen.getByText("Teraz nie si na rade.")).toBeTruthy();
  });
});
