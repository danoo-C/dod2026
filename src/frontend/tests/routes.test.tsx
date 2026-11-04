// Each route is its screen, with its own connection and role (plan steps 1-2).
import { act, cleanup, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routes, SCREENS } from "../src/routes";
import { FakeWebSocket, install } from "./support/fakes";

beforeEach(() => {
  vi.useFakeTimers();
  install();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("routes", () => {
  it("has the three screens of tech-spec 5.1, each with its role", () => {
    expect(SCREENS).toEqual([
      { path: "/", role: "phone" },
      { path: "/internal/main", role: "main" },
      { path: "/internal/logging", role: "logging" },
    ]);
  });

  it.each(SCREENS)("$path connects as $role", async ({ path, role }) => {
    render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(FakeWebSocket.last.url).toBe(`ws://localhost:3000/ws?role=${role}`);
    act(() => FakeWebSocket.last.accept());
  });

  it.each(SCREENS.filter((s) => s.role === "main"))("$path is still the hello page", async ({ path, role }) => {
    render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
    expect(screen.getByText(role)).toBeTruthy();
    expect(screen.getByTestId("status").textContent).toBe("Pripájam…");
    await act(() => vi.advanceTimersByTimeAsync(0));
    act(() => FakeWebSocket.last.accept());
    expect(screen.getByTestId("status").textContent).toBe("Pripojené");
    expect(screen.getByTestId("session").textContent).toBe("7f3a");
  });

  it("/internal/logging is the terminal", () => {
    render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: ["/internal/logging"] })} />);
    expect(screen.getByRole("region", { name: "Terminál" })).toBeTruthy();
  });
});
