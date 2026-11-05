// From the analyser's frequency bins to the 32 bands the backend wants
// (tech-spec 5.2; plan step 7).
//
// The bins are linear in frequency (each sampleRate / fftSize wide), hearing
// is logarithmic: the bands are spaced logarithmically from LOW to HIGH Hz,
// so the bass gets as many bands as the treble. Each band is the average of
// its bins (the analyser gives 0-255, already in decibels: MIN_DB to MAX_DB).
//
// Two ways on from there:
// - the lights (LightLevels): tilted towards the treble, and only the top
//   WINDOW_DB below the recent peak lit, so quiet parts go dark
// - the beat (AutoGain, then beat.ts): untilted, where the kick drum is

export const BANDS = 32;
export const LOW_HZ = 40;
export const HIGH_HZ = 16000;

// The analyser's byte range: 0 is MIN_DB, 255 is MAX_DB (dBFS). The top is
// well above the browser's default -30, so a loud bass doesn't flatten at 255.
export const MIN_DB = -100;
export const MAX_DB = -10;

// --- the lights' shape; the values to tune by eye on the real strip ---------
/** dB added per octave above PIVOT_HZ (taken off below): music has far more
 * energy in the bass, so without it the low bands outshine everything. */
export const TILT_DB_PER_OCTAVE = 4.5;
export const PIVOT_HZ = 1000;
/** How many dB below the recent peak still give light; anything quieter is dark. */
export const WINDOW_DB = 30;
/** Above 1: the window's lower part stays dimmer, the top punchier. */
export const CURVE = 1.6;
/** How fast the peak follows a quieter song down, in dB per frame (~3 dB/s at 30 a second). */
export const PEAK_FALL_DB = 0.1;
/** The peak never goes below this level (on the 0-90 dB scale above MIN_DB),
 * so near-silence isn't blown up into light. */
export const PEAK_FLOOR_DB = 50;

/** [first, last] bin of each band; every band has at least one bin. */
export function bandEdges(sampleRate: number, fftSize: number, count = BANDS, low = LOW_HZ, high = HIGH_HZ): [number, number][] {
  const binHz = sampleRate / fftSize;
  const bins = fftSize / 2;
  const edges: [number, number][] = [];
  let next = Math.max(1, Math.floor(low / binHz)); // bin 0 is DC
  for (let i = 0; i < count; i++) {
    const top = low * (high / low) ** ((i + 1) / count);
    const last = Math.min(bins - 1, Math.max(next, Math.round(top / binHz) - 1));
    edges.push([next, last]);
    next = Math.min(bins - 1, last + 1);
  }
  return edges;
}

/** Each band's average, 0-1 (the bins are 0-255). */
export function toBands(bins: ArrayLike<number>, edges: readonly [number, number][]): number[] {
  return edges.map(([first, last]) => {
    let sum = 0;
    for (let b = first; b <= last; b++) sum += bins[b] ?? 0;
    return sum / (last - first + 1) / 255;
  });
}

/** Each band's geometric centre in Hz. */
export function bandCentres(count = BANDS, low = LOW_HZ, high = HIGH_HZ): number[] {
  return Array.from({ length: count }, (_, i) => low * (high / low) ** ((i + 0.5) / count));
}

/**
 * The bands as the lights show them, 0-1. Each band in dB (from toBands'
 * 0-1), tilted by TILT_DB_PER_OCTAVE around PIVOT_HZ; the loudest tilted band
 * sets the peak (it jumps up at once, falls PEAK_FALL_DB a frame, never below
 * PEAK_FLOOR_DB); a band WINDOW_DB or more below the peak is 0, at the peak 1,
 * shaped by CURVE in between. Silence stays dark, and a quiet passage dims the
 * strip instead of leaving it half lit.
 */
export class LightLevels {
  private readonly tilt: number[];
  private peak = PEAK_FLOOR_DB;

  constructor(count = BANDS) {
    this.tilt = bandCentres(count).map((hz) => TILT_DB_PER_OCTAVE * Math.log2(hz / PIVOT_HZ));
  }

  apply(bands: readonly number[]): number[] {
    const range = MAX_DB - MIN_DB;
    // a band with nothing in it stays at -Infinity: the tilt can't light silence
    const levels = bands.map((b, i) => (b > 0 ? b * range + (this.tilt[i] ?? 0) : -Infinity));
    this.peak = Math.max(PEAK_FLOOR_DB, ...levels, this.peak - PEAK_FALL_DB);
    const bottom = this.peak - WINDOW_DB;
    return levels.map((l) => Math.min(1, Math.max(0, (l - bottom) / WINDOW_DB)) ** CURVE);
  }
}

/**
 * For the beat detector: a slow automatic gain, the loudest band of the last
 * few seconds becomes 1.
 * The peak follows a louder moment at once and lets go slowly (DECAY per
 * frame), with a floor, so silence isn't blown up into noise.
 */
export class AutoGain {
  private peak: number;

  constructor(
    private readonly decay = 0.995, // per frame: at 30 a second, about halving in 4-5 s
    private readonly floor = 0.15,
  ) {
    this.peak = floor;
  }

  apply(bands: readonly number[]): number[] {
    const loudest = Math.max(0, ...bands);
    this.peak = Math.max(this.floor, loudest, this.peak * this.decay);
    return bands.map((b) => Math.min(1, b / this.peak));
  }
}
