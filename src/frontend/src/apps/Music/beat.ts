// A beat: the low bands' energy jumping above its own recent average (plan
// step 7). Simple, and good enough for a kick drum lighting up the strip:
//
//   energy  = average of the lowest LOW_BANDS bands (~40-150 Hz)
//   beat    = energy > RATIO × its average over the last WINDOW seconds,
//             and above MIN_ENERGY, and at least GAP seconds after the last
//
// A steady sound (a held note, noise – flat after the analyser's smoothing)
// has no jumps, so no beats.

export const LOW_BANDS = 4;
export const WINDOW = 1.0; // seconds of history
export const RATIO = 1.4;
export const MIN_ENERGY = 0.15;
export const GAP = 0.34; // seconds: at most ~2.9 beats a second (176 BPM): each beat is a burst on the strip, and the flash limit allows 3 a second

export class BeatDetector {
  private history: { t: number; energy: number }[] = [];
  private last = -Infinity;

  /** One frame's bands (0-1) at time `t` (seconds); true on a beat. */
  push(bands: readonly number[], t: number): boolean {
    const low = bands.slice(0, LOW_BANDS);
    const energy = low.reduce((a, b) => a + b, 0) / Math.max(1, low.length);
    while (this.history.length > 0 && (this.history[0]?.t ?? t) < t - WINDOW) this.history.shift();
    const average = this.history.length === 0 ? energy : this.history.reduce((a, h) => a + h.energy, 0) / this.history.length;
    this.history.push({ t, energy });
    if (energy > MIN_ENERGY && energy > RATIO * average && t - this.last >= GAP) {
      this.last = t;
      return true;
    }
    return false;
  }
}
