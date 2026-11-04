// The fake loading screen (tech-spec 5.1; plan step 3): 2-4 s of a ring,
// steps that tick off and hex flying by. When it starts it sends
// `loading_started`, so the terminal on the notebook bursts at the same
// moment (backend.md 10) – both look like they do the same heavy work.
import { useEffect, useRef, useState } from "react";

import { useSend } from "../api/useStand";

export const STEPS = [
  "Inicializujem fotónovú zbernicu",
  "Kalibrujem RGB jadro",
  "Synchronizujem 8×8 mriežku",
  "Načítavam spektrálny analyzátor",
  "Overujem kvantovú entropiu",
  "Pripravujem svetelnú show",
];
export const MIN_MS = 2000;
export const MAX_MS = 4000;
const FRAME_MS = 60;
const HOLD_MS = 350; // at 100 % for a moment before it goes
const RING = 276.5; // the arc's length, 2π · 44

function hexLine(random: () => number): string {
  let s = "0x";
  for (let i = 0; i < 60; i++) s += Math.floor(random() * 16).toString(16);
  return s;
}

export interface LoadingScreenProps {
  /** Called once, after the screen has run its time. */
  onDone?: () => void;
  title?: string;
  /** Fixed length in ms, the pause at 100 % included; otherwise random, 2-4 s. */
  durationMs?: number;
  random?: () => number;
}

export function LoadingScreen({ onDone, title = "Pripravujem…", durationMs, random = Math.random }: LoadingScreenProps) {
  const send = useSend();
  // the whole time, from the first frame to onDone: the ring runs for all of it
  // but the pause at 100 %, and a frame's worth is kept free so it ends by MAX_MS
  const [duration] = useState(() => durationMs ?? MIN_MS + random() * (MAX_MS - MIN_MS - 2 * FRAME_MS));
  const [progress, setProgress] = useState(0);
  const [hex, setHex] = useState(() => hexLine(random));
  const started = useRef<number | null>(null);
  const sent = useRef(false);
  const done = useRef(false);
  // in refs, so a caller's new function on every render doesn't restart the clock
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;
  const randomRef = useRef(random);
  randomRef.current = random;

  useEffect(() => {
    // refs survive React's StrictMode double mount: one message, one clock
    if (!sent.current) {
      sent.current = true;
      send({ type: "loading_started" });
    }
    started.current ??= performance.now();
    let hold: ReturnType<typeof setTimeout> | null = null;
    const id = setInterval(() => {
      const p = Math.min(1, (performance.now() - (started.current ?? 0)) / Math.max(FRAME_MS, duration - HOLD_MS));
      setProgress(p);
      setHex(hexLine(randomRef.current));
      if (p >= 1) {
        clearInterval(id);
        hold = setTimeout(() => {
          if (done.current) return;
          done.current = true;
          onDoneRef.current?.();
        }, HOLD_MS);
      }
    }, FRAME_MS);
    return () => {
      clearInterval(id);
      if (hold !== null) clearTimeout(hold);
    };
  }, [duration, send]);

  const eased = 1 - Math.pow(1 - progress, 2.2);
  const current = Math.min(STEPS.length - 1, Math.floor(eased * STEPS.length));
  return (
    <div className="load" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(eased * 100)} aria-label={title}>
      <h2>{title}</h2>
      <div className="ring">
        <span className="spin" />
        <svg viewBox="0 0 100 100" aria-hidden="true">
          <defs>
            <linearGradient id="load-ring">
              <stop offset="0" stopColor="var(--hot)" />
              <stop offset="1" stopColor="var(--warm)" />
            </linearGradient>
          </defs>
          <circle cx="50" cy="50" r="44" fill="none" stroke="var(--line)" strokeWidth="6" />
          <circle
            cx="50"
            cy="50"
            r="44"
            fill="none"
            stroke="url(#load-ring)"
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={RING}
            strokeDashoffset={RING * (1 - eased)}
          />
        </svg>
        <span className="pct">{Math.round(eased * 100)} %</span>
      </div>
      <div className="steps">
        {STEPS.map((step, i) => (
          <div key={step} className={i < current || progress >= 1 ? "done" : i === current ? "now" : "todo"}>
            {step}
          </div>
        ))}
      </div>
      <div className="hex" aria-hidden="true">
        {hex}
      </div>
    </div>
  );
}
