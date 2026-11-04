// mm:ss until a server time, on the server's clock (backend.md 6; plan step 3).
// A phone 30 s off still shows the server's seconds.
import { useEffect, useState } from "react";

import { formatSeconds } from "../api/clock";
import { useServerClock } from "../api/useStand";

const TICK_MS = 250; // a second never shows up to a whole second late
const RING = 263.9; // the timer arc's length, 2π · 42

/** Re-render every `ms` while mounted. */
export function useTick(ms: number = TICK_MS): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
}

export interface CountdownProps {
  /** Server time, in seconds; null shows dashes. */
  to: number | null;
  /** With a total (seconds), a ring around it shows how much is left, like the phone's turn timer. */
  total?: number;
}

export function Countdown({ to, total }: CountdownProps) {
  const clock = useServerClock();
  useTick();
  const left = to === null ? null : clock.secondsUntil(to);
  const text = (
    <b className="countdown" data-testid="countdown">
      {left === null ? "–:––" : formatSeconds(left)}
    </b>
  );
  if (total === undefined) return text;
  const fraction = left === null || total <= 0 ? 0 : Math.min(1, left / total);
  return (
    <div className="timer">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle cx="50" cy="50" r="42" fill="none" stroke="var(--line)" strokeWidth="9" />
        <circle
          cx="50"
          cy="50"
          r="42"
          fill="none"
          stroke="var(--hot)"
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={RING}
          strokeDashoffset={RING * (1 - fraction)}
        />
      </svg>
      {text}
    </div>
  );
}
