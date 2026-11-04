// A placeholder per route (plan steps 1-2): which screen this is, and what its
// connection knows. Replaced by the real screens in steps 4-6.
import type { Role } from "../api/roles";
import { useServerClock, useStand, useStandActions } from "../api/useStand";
import { LiveBadge } from "../components/Badge";
import { STATUS_TEXT } from "../components/Connection";
import { Countdown } from "../components/Countdown";
import { LivePreview } from "../components/Preview";
import { LiveTerminal } from "../components/Terminal";
import { LiveToast } from "../components/Toast";

const NAMES: Record<Role, string> = {
  phone: "Mobil návštevníka",
  main: "Obrazovka notebooku",
  logging: "Terminál",
};

export function Hello({ role }: { role: Role }) {
  const status = useStand((s) => s.status);
  const welcome = useStand((s) => s.welcome);
  const state = useStand((s) => s.state);
  const you = useStand((s) => s.you);
  const lines = useStand((s) => s.log.length);
  const clock = useServerClock();
  const { send } = useStandActions();

  const turnEnds = you?.turn_ends_at ?? state?.queue.turn_ends_at ?? null;

  return (
    <main style={{ padding: "2rem 16px", maxWidth: 900, margin: "0 auto" }}>
      <h1 style={{ font: "800 28px/1.1 var(--f-display)" }}>DOD 2026</h1>
      <p>
        {NAMES[role]} (<code>{role}</code>) <LiveBadge />
      </p>
      <LivePreview size="large" />
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
        <dd>
          <Countdown to={turnEnds} />
        </dd>
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
      {role !== "phone" && (
        <div style={{ height: 320, border: "1px solid var(--line)", borderRadius: 10, overflow: "hidden" }}>
          <LiveTerminal />
        </div>
      )}
      <LiveToast />
    </main>
  );
}
