// The three screens, picked by the URL (tech-spec 5.1). Each one has its
// WebSocket role (backend.md 9) and its own connection. The main screen
// connects only after "Spustiť" (StartGate): until then it isn't the player.
import type { ReactNode } from "react";
import type { RouteObject } from "react-router";

import type { Role } from "./api/roles";
import { StandProvider } from "./api/useStand";
import { ConnectionGate } from "./components/Connection";
import { Logging } from "./screens/Logging";
import { Main, StartGate } from "./screens/Main";
import { Phone } from "./screens/Phone";

export const SCREENS: { path: string; role: Role }[] = [
  { path: "/", role: "phone" },
  { path: "/internal/main", role: "main" },
  { path: "/internal/logging", role: "logging" },
];

const SCREEN: Record<Role, () => ReactNode> = {
  phone: () => <Phone />,
  main: () => <Main />,
  logging: () => <Logging />,
};

function connected(role: Role): ReactNode {
  return (
    <StandProvider role={role}>
      <ConnectionGate>{SCREEN[role]()}</ConnectionGate>
    </StandProvider>
  );
}

export const routes: RouteObject[] = SCREENS.map(({ path, role }) => ({
  path,
  element: role === "main" ? <StartGate>{connected(role)}</StartGate> : connected(role),
}));
