// A placeholder per route (plan steps 1-2): which screen this is, and what its
// connection knows. Replaced by the real screens in steps 4-6.
import { useEffect, useState } from "react";

import { formatSeconds } from "../api/clock";
import type { Role } from "../api/roles";
import { useServerClock, useStand, useStandActions } from "../api/useStand";
import { STATUS_TEXT } from "../components/Connection";

const NAMES: Record<Role, string> = {
  phone: "Mobil návštevníka",
  main: "Obrazovka notebooku",
  logging: "Terminál",
};

/** Re-render once a second, for countdowns. */
function useSecondTick(): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
}

export function Hello({ role }: { role: Role }) {
  const status = useStand((s) => s.status);
  const welcome = useStand((s) => s.welcome);
  const state = useStand((s) => s.state);
  const you = useStand((s) => s.you);
  const toast = useStand((s) => s.toast);
  const lines = useStand((s) => s.log.length);
  const clock = useServerClock();
  const { send } = useStandActions();
  useSecondTick();

  const turnEnds = you?.turn_ends_at ?? state?.queue.turn_ends_at ?? null;

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", color: "#eef0fb" }}>
      <h1>DOD 2026</h1>
      <p>
        {NAMES[role]} (<code>{role}</code>)
      </p>
      <dl>
        <dt>Spojenie</dt>
        <dd data-testid="status">{STATUS_TEXT[status]}</dd>
        <dt>Relácia</dt>
        <dd data-testid="session">{welcome?.session ?? "–"}</dd>
        <dt>Režim</dt>
        <dd>{state?.mode ?? "–"}</dd>
        <dt>Rad</dt>
        <dd>
          ovláda {state?.queue.controller ?? "nikto"}, čaká {state?.queue.waiting ?? 0}
          {you !== null && you.position !== null && ` · ty: ${you.position === 0 ? "ovládaš" : `${you.position}.`}`}
        </dd>
        <dt>Koniec ťahu</dt>
        <dd data-testid="countdown">{turnEnds === null ? "–" : formatSeconds(clock.secondsUntil(turnEnds))}</dd>
        <dt>Rozdiel hodín</dt>
        <dd>{(clock.offsetMs / 1000).toFixed(1)} s</dd>
        {role !== "phone" && (
          <>
            <dt>Riadky logu</dt>
            <dd>{lines}</dd>
          </>
        )}
      </dl>
      {role === "phone" && (
        <p>
          <button type="button" onClick={() => send({ type: "join_queue" })}>
            Postaviť sa do radu
          </button>{" "}
          <button type="button" onClick={() => send({ type: "leave_queue" })}>
            Odísť z radu
          </button>
        </p>
      )}
      {toast !== null && <p role="status">{toast.text}</p>}
    </main>
  );
}
