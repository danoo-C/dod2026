// What a screen shows about its connection (plan step 2):
//
// - replaced, forbidden, broken: the whole screen, instead of the screen itself
//   (nothing else on it would work)
// - offline: a strip on top, the screen stays (it shows the last state, greyed by its own rules)
// - connecting: the screen, which shows its own "loading" until the first state
import type { ReactNode } from "react";

import type { Status } from "../api/socket";
import { useStand, useStandActions } from "../api/useStand";

export const STATUS_TEXT: Record<Status, string> = {
  connecting: "Pripájam…",
  open: "Pripojené",
  offline: "Odpojené, pripájam znova…",
  replaced: "Otvorené v inom okne",
  forbidden: "Sem nemáš prístup",
  broken: "Chyba stránky",
};

export function ConnectionGate({ children }: { children: ReactNode }) {
  const status = useStand((s) => s.status);
  const { takeOver, role } = useStandActions();

  if (status === "replaced") {
    return (
      <Blocked title={STATUS_TEXT.replaced}>
        <p>Obrazovka stánku je otvorená v inom okne. Hudbu hrá to druhé.</p>
        <button type="button" onClick={takeOver}>
          Prevziať
        </button>
      </Blocked>
    );
  }
  if (status === "forbidden") {
    return (
      <Blocked title={STATUS_TEXT.forbidden}>
        <p>
          {role === "phone"
            ? "Táto stránka sa nedá otvoriť."
            : "Táto stránka je len pre notebook pri stánku. Otvor ju zo spúšťača (start.bat), ten pridá kľúč."}
        </p>
      </Blocked>
    );
  }
  if (status === "broken") {
    return (
      <Blocked title={STATUS_TEXT.broken}>
        <p>Stránka sa pýta na niečo, čo server nepozná. Toto je chyba v aplikácii.</p>
      </Blocked>
    );
  }
  return (
    <>
      {status === "offline" && (
        <div role="status" data-testid="offline" style={offlineStyle}>
          {STATUS_TEXT.offline}
        </div>
      )}
      {children}
    </>
  );
}

function Blocked({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main role="alert" style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", color: "#eef0fb" }}>
      <h1>{title}</h1>
      {children}
    </main>
  );
}

// plain styles until step 3 brings the mockup's
const offlineStyle = {
  position: "fixed",
  insetInline: 0,
  top: 0,
  padding: "6px 12px",
  background: "#ffb238",
  color: "#0c0d18",
  fontFamily: "system-ui, sans-serif",
  fontWeight: 700,
  textAlign: "center",
} as const;
