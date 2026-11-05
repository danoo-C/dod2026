// The main screen's hidden admin panel (tech-spec 4.6, 5.1; plan step 6):
// Ctrl+Alt+D opens it, Esc closes it. It isn't in the page until opened, so
// visitors never see it. Skip the current person, pause the queue, stop the
// song, the terminal's width, and the board's status in full.
// Ctrl+Alt+K skips the current person without the panel (someone left early).
import { useEffect, useRef, useState } from "react";

import { useStand, useStandActions } from "../api/useStand";
import { LiveBadge } from "./Badge";

export const STATUS_POLL_MS = 2000;
export const TERM_MIN = 25;
export const TERM_MAX = 33;
export const KICK_COOLDOWN_MS = 3000; // a second Ctrl+Alt+K this soon is ignored: the next person keeps their turn

/** Ctrl+Alt+<key>, wherever the focus is. By key position (e.code), so a Slovak keyboard's AltGr works too. */
function isCtrlAlt(e: KeyboardEvent, code: string): boolean {
  return e.ctrlKey && e.altKey && !e.shiftKey && !e.metaKey && e.code === code;
}

/** Ctrl+Alt+D: open the panel. */
export function isAdminShortcut(e: KeyboardEvent): boolean {
  return isCtrlAlt(e, "KeyD");
}

/** Ctrl+Alt+K: skip the current person. */
export function isKickShortcut(e: KeyboardEvent): boolean {
  return isCtrlAlt(e, "KeyK");
}

/**
 * Ctrl+Alt+K skips the current person, like the panel's first button. Held
 * down or pressed twice quickly, it still skips only one person.
 */
export function useKickShortcut(): void {
  const { send } = useStandActions();
  const controller = useStand((s) => s.state?.queue.controller ?? null);
  const ref = useRef({ send, controller, last: -Infinity });
  ref.current.send = send;
  ref.current.controller = controller;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!isKickShortcut(e)) return;
      e.preventDefault();
      const r = ref.current;
      const now = Date.now();
      if (e.repeat || r.controller === null || now - r.last < KICK_COOLDOWN_MS) return;
      r.last = now;
      r.send({ type: "admin", action: "skip" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

export function useAdminShortcut(open: () => void): void {
  const openRef = useRef(open);
  openRef.current = open;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!isAdminShortcut(e)) return;
      e.preventDefault();
      openRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

type Status = Record<string, unknown>;

/** /api/status while the panel is open (backend.md 5.6). */
function useBackendStatus(): Status | null {
  const [status, setStatus] = useState<Status | null>(null);
  useEffect(() => {
    let stop = false;
    const poll = async () => {
      try {
        const r = await fetch("/api/status", { cache: "no-store" });
        if (!stop && r.ok) setStatus((await r.json()) as Status);
      } catch {
        if (!stop) setStatus(null);
      }
    };
    void poll();
    const id = setInterval(() => void poll(), STATUS_POLL_MS);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, []);
  return status;
}

function get(o: unknown, ...path: string[]): unknown {
  let v: unknown = o;
  for (const k of path) v = v !== null && typeof v === "object" ? (v as Record<string, unknown>)[k] : undefined;
  return v;
}

function show(v: unknown): string {
  if (v === null || v === undefined) return "–";
  if (Array.isArray(v)) return v.join(", ") || "–";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function AdminPanel({
  onClose,
  termWidth,
  setTermWidth,
}: {
  onClose(): void;
  termWidth: number;
  setTermWidth(width: number): void;
}) {
  const { send } = useStandActions();
  const queue = useStand((s) => s.state?.queue ?? null);
  const song = useStand((s) => s.state?.music.title ?? s.state?.music.song ?? null);
  const status = useBackendStatus();
  const first = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows: [string, unknown][] = [
    ["Spojenie s doskou", get(status, "link", "state")],
    ["Port", get(status, "link", "url")],
    ["Firmvér", get(status, "link", "device", "firmware")],
    ["LED", get(status, "render", "led_count")],
    ["Snímky / s (doska)", get(status, "link", "fps")],
    ["Snímky / s (render)", get(status, "render", "fps")],
    ["Odozva (ms)", get(status, "link", "rtt_ms")],
    ["Odoslané snímky", get(status, "link", "frames_sent")],
    ["Opätovné pripojenia", get(status, "link", "reconnects")],
    ["Posledná chyba", get(status, "link", "last_error")],
    ["Úlohy", get(status, "tasks", "running")],
    ["Reštarty úloh", get(status, "tasks", "restarts")],
    ["Pripojené prehliadače", get(status, "connections")],
  ];

  return (
    <div className="admin-backdrop" onClick={onClose}>
      <section
        className="admin"
        role="dialog"
        aria-modal="true"
        aria-label="Správa stánku"
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <h2>Správa stánku</h2>
          <LiveBadge />
          <button type="button" className="ghost" onClick={onClose} aria-label="Zavrieť (Esc)">
            ✕
          </button>
        </header>
        <div className="admin-actions">
          <button
            ref={first}
            type="button"
            disabled={queue?.controller === null || queue === null}
            onClick={() => send({ type: "admin", action: "skip" })}
          >
            Preskočiť toho, kto ovláda
          </button>
          {queue?.paused ? (
            <button type="button" onClick={() => send({ type: "admin", action: "resume_queue" })}>
              Spustiť rad
            </button>
          ) : (
            <button type="button" onClick={() => send({ type: "admin", action: "pause_queue" })}>
              Pozastaviť rad
            </button>
          )}
          <button type="button" disabled={song === null} onClick={() => send({ type: "admin", action: "stop_song" })}>
            Zastaviť skladbu
          </button>
        </div>
        <p className="note">
          Rad: {queue === null ? "–" : `ovláda ${queue.controller ?? "nikto"}, čaká ${queue.waiting}${queue.paused ? ", pozastavený" : ""}`}
          {song !== null && ` · hrá ${song}`}
        </p>
        <label className="admin-width">
          Šírka terminálu
          <input
            type="range"
            min={TERM_MIN}
            max={TERM_MAX}
            step={1}
            value={termWidth}
            onChange={(e) => setTermWidth(Number(e.currentTarget.value))}
          />
          <output>{termWidth} %</output>
        </label>
        <dl className="admin-status" aria-label="Stav">
          {rows.map(([name, value]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{show(value)}</dd>
            </div>
          ))}
        </dl>
        <p className="note">
          Zatvoríš klávesom Esc. Otvoríš znova Ctrl+Alt+D. Ctrl+Alt+K preskočí toho, kto ovláda, aj bez panela.
        </p>
      </section>
    </div>
  );
}
