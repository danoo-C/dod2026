// Which screen the phone shows (plan step 5). It comes from `you` alone, so a
// reload lands on the right one; the only memory is whether this page just
// saw its own turn start (then the loading screen runs first) or end.
//
//   not in the queue, no turn seen   welcome      "Postaviť sa do radu"
//   waiting (position ≥ 1)           waiting      "Si 3. v poradí"
//   in control, just got it          loading      2-4 s, then:
//   in control                       control      the controls
//   not in the queue, turn seen      ended        "Tvoj čas skončil"
import { useState } from "react";

import type { QueuePart, You } from "../api/messages";
import type { ServerClock } from "../api/clock";

export type PhoneScreen = "connecting" | "welcome" | "waiting" | "loading" | "control" | "ended";

export function phoneScreen(you: You | null, turnSeen: boolean, loading: boolean): PhoneScreen {
  if (you === null) return "connecting";
  if (you.in_control) return loading ? "loading" : "control";
  if (you.position !== null && you.position >= 1) return "waiting";
  return turnSeen ? "ended" : "welcome";
}

/** The screen, following `you` as it changes. */
export function usePhoneScreen(you: You | null): { screen: PhoneScreen; loaded(): void } {
  const [before, setBefore] = useState<You | null>(null);
  const [turnSeen, setTurnSeen] = useState(false);
  const [loading, setLoading] = useState(false);

  // Adjusted while rendering, not in an effect: an effect would show the
  // controls for one frame before the loading screen.
  if (you !== before) {
    setBefore(you);
    if (you !== null && you.in_control) {
      if (!turnSeen) setTurnSeen(true);
      // only when this page saw them wait: a reload in the middle of a turn goes straight to the controls
      if (before !== null && !before.in_control && !loading) setLoading(true);
    } else if (you !== null) {
      if (loading) setLoading(false);
      if (you.position !== null && turnSeen) setTurnSeen(false); // queued again: the next end is a new one
    }
  }

  return { screen: phoneScreen(you, turnSeen, loading), loaded: () => setLoading(false) };
}

/**
 * Roughly how long until this phone's turn, in seconds: the rest of the
 * current turn, and a full turn for everyone ahead. A turn can end sooner
 * (a song, inactivity), so this is "about".
 */
export function waitSeconds(position: number, queue: QueuePart, turnSeconds: number, clock: ServerClock): number {
  const current =
    queue.controller === null || queue.turn_over || queue.turn_ends_at === null ? 0 : clock.secondsUntil(queue.turn_ends_at);
  return current + Math.max(0, position - 1) * turnSeconds;
}
