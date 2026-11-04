// From the analyser's frequency bins to the 32 bands the backend wants
// (tech-spec 5.2; plan step 7).
//
// The bins are linear in frequency (each sampleRate / fftSize wide), hearing
// is logarithmic: the bands are spaced logarithmically from LOW to HIGH Hz,
// so the bass gets as many bands as the treble. Each band is the average of
// its bins (the analyser gives 0-255, already in decibels), then scaled by a
// slow automatic gain, so a quiet song moves the lights as much as a loud one.

export const BANDS = 32;
export const LOW_HZ = 40;
export const HIGH_HZ = 16000;

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

/**
 * A slow automatic gain: the loudest band of the last few seconds becomes 1.
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
