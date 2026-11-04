// The three screens, picked by the URL (tech-spec 5.1). Each one has its
// WebSocket role (backend.md 9) and its own connection. The main screen
// isn't built yet (plan step 6): it shows the hello page.
import type { ReactNode } from "react";
import type { RouteObject } from "react-router";

import type { Role } from "./api/roles";
import { StandProvider } from "./api/useStand";
import { ConnectionGate } from "./components/Connection";
import { Hello } from "./screens/Hello";
import { Logging } from "./screens/Logging";
import { Phone } from "./screens/Phone";

export const SCREENS: { path: string; role: Role }[] = [
  { path: "/", role: "phone" },
  { path: "/internal/main", role: "main" },
  { path: "/internal/logging", role: "logging" },
];

const SCREEN: Record<Role, () => ReactNode> = {
  phone: () => <Phone />,
  main: () => <Hello role="main" />,
  logging: () => <Logging />,
};

export const routes: RouteObject[] = SCREENS.map(({ path, role }) => ({
  path,
  element: (
    <StandProvider role={role}>
      <ConnectionGate>{SCREEN[role]()}</ConnectionGate>
    </StandProvider>
  ),
}));
