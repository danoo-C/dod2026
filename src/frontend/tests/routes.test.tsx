// Each route shows its screen and asks the backend whether it runs (plan step 1).
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { routes, SCREENS } from "../src/routes";

afterEach(cleanup);

function show(path: string) {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
}

describe("routes", () => {
  it("has the three screens of tech-spec 5.1, each with its role", () => {
    expect(SCREENS).toEqual([
      { path: "/", role: "phone" },
      { path: "/internal/main", role: "main" },
      { path: "/internal/logging", role: "logging" },
    ]);
  });

  it.each(SCREENS)("$path shows the $role screen and a running backend", async ({ path, role }) => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ status: "ok" })));
    vi.stubGlobal("fetch", fetch);
    show(path);
    expect(screen.getByText(role)).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("health").textContent).toBe("Backend: beží"));
    expect(fetch).toHaveBeenCalledWith("/api/health");
  });

  it("says when the backend doesn't answer", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 502 })));
    show("/");
    await waitFor(() => expect(screen.getByTestId("health").textContent).toBe("Backend: neodpovedá"));
  });
});
