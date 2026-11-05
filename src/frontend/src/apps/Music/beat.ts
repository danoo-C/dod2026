// The kick drum: a sudden rise of the lowest bands (spectral flux).
//
// The analyser's bands are already in decibels (0-1 over MIN_DB..MAX_DB), so
// a kick is a jump of a few dB, not a multiple of the level: comparing the
// level with its average (the first version) found 4-38 kicks in a whole song.
// Instead, per frame:
//
//   flux = how many dB the LOW_BANDS lowest bands (~40-150 Hz) rose since
//          the last frame, on average (falls count as 0)
//   kick = flux > MIN_FLUX_DB, and an outlier: > mean + K × spread of the
//          flux over the last WINDOW seconds, and GAP seconds after the last
//
// Tuned on the 10 songs of the stand (their real spectra, computed offline
// the way the browser does): most of the kicks of a four-on-the-floor song,
// ~80-90 % of them on the beat grid. A steady sound has no rises: no kicks.

import { MAX_DB, MIN_DB } from "./spectrum";

export const LOW_BANDS = 5;
export const WINDOW = 1.5; // seconds of flux history
export const K = 1.5;
export const MIN_FLUX_DB = 3;
export const GAP = 0.34; // seconds: at most ~2.9 kicks a second (176 BPM); each is a hit on the strip, and the flash limit allows 3 flashes a second

export class BeatDetector {
  private history: { t: number; flux: number }[] = [];
  private previous: number[] | null = null;
  private last = -Infinity;

  /** One frame's bands (0-1, from toBands) at time `t` (seconds); true on a kick. */
  push(bands: readonly number[], t: number): boolean {
    const low = bands.slice(0, LOW_BANDS);
    const before = this.previous ?? low;
    this.previous = low;
    let rise = 0;
    for (let i = 0; i < low.length; i++) rise += Math.max(0, (low[i] ?? 0) - (before[i] ?? 0));
    const flux = (rise / Math.max(1, low.length)) * (MAX_DB - MIN_DB);

    while (this.history.length > 0 && (this.history[0]?.t ?? t) < t - WINDOW) this.history.shift();
    const n = this.history.length;
    const mean = n === 0 ? 0 : this.history.reduce((a, h) => a + h.flux, 0) / n;
    const spread = n < 2 ? 0 : Math.sqrt(this.history.reduce((a, h) => a + (h.flux - mean) ** 2, 0) / n);
    this.history.push({ t, flux });

    if (flux > MIN_FLUX_DB && flux > mean + K * spread && t - this.last >= GAP) {
      this.last = t;
      return true;
    }
    return false;
  }
}
