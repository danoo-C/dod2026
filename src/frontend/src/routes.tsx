// The three screens, picked by the URL (tech-spec 5.1). Each one has its
// WebSocket role (backend.md 9). Until the screens exist (plan steps 4-6),
// every route shows the hello page.
import type { RouteObject } from "react-router";

import type { Role } from "./api/roles";
import { Hello } from "./screens/Hello";

export const SCREENS: { path: string; role: Role }[] = [
  { path: "/", role: "phone" },
  { path: "/internal/main", role: "main" },
  { path: "/internal/logging", role: "logging" },
];

export const routes: RouteObject[] = SCREENS.map(({ path, role }) => ({
  path,
  element: <Hello role={role} />,
}));
