// The spectrum and the beat on the main screen (plan step 7), from synthetic
// analyser data.
import { describe, expect, it } from "vitest";

import { BeatDetector, GAP, MIN_FLUX_DB } from "../src/apps/Music/beat";
import {
  BANDS,
  bandCentres,
  bandEdges,
  HIGH_HZ,
  LightLevels,
  LOW_HZ,
  MAX_DB,
  MIN_DB,
  TILT_DB_PER_OCTAVE,
  toBands,
  WINDOW_DB,
} from "../src/apps/Music/spectrum";

const RATE = 48000;
const FFT = 2048;
const BIN_HZ = RATE / FFT; // 23.4 Hz

describe("bandEdges", () => {
  const edges = bandEdges(RATE, FFT);

  it("32 bands from 40 Hz to 16 kHz, in order, each at least one bin, none overlapping", () => {
    expect(edges).toHaveLength(BANDS);
    expect(edges[0]?.[0]).toBe(Math.floor(LOW_HZ / BIN_HZ));
    expect((edges.at(-1)?.[1] ?? 0) * BIN_HZ).toBeCloseTo(HIGH_HZ, -3);
    for (let i = 0; i < edges.length; i++) {
      const [first, last] = edges[i] ?? [0, 0];
      expect(last).toBeGreaterThanOrEqual(first);
      if (i > 0) expect(first).toBe((edges[i - 1]?.[1] ?? 0) + 1);
    }
  });

  it("logarithmic: the bass gets narrow bands, the treble wide ones", () => {
    const width = (i: number) => (edges[i]?.[1] ?? 0) - (edges[i]?.[0] ?? 0) + 1;
    expect(width(0)).toBe(1);
    expect(width(31)).toBeGreaterThan(50);
  });

  it("44.1 kHz too (a different sound card)", () => {
    expect(bandEdges(44100, FFT)).toHaveLength(BANDS);
  });
});

describe("toBands", () => {
  const edges = bandEdges(RATE, FFT);

  it("a known spectrum gives the expected bands", () => {
    const bins = new Uint8Array(FFT / 2);
    const at = (hz: number) => Math.round(hz / BIN_HZ);
    bins[at(60)] = 255; // a bass note
    for (let b = at(3000); b < at(7000); b++) bins[b] = 128; // a hiss, wider than the band around 4.5 kHz
    const bands = toBands(bins, edges);
    expect(bands).toHaveLength(32);
    const loudest = bands.indexOf(Math.max(...bands));
    expect(loudest).toBeLessThan(5); // the bass is in the first bands
    const hiss = edges.findIndex(([f, l]) => f <= at(4500) && at(4500) <= l);
    expect(bands[hiss]).toBeCloseTo(128 / 255, 1);
    expect(bands[BANDS - 1]).toBe(0); // nothing up at 16 kHz
    expect(bands.every((b) => b >= 0 && b <= 1)).toBe(true);
  });

  it("silence is all 0, full scale all 1", () => {
    expect(toBands(new Uint8Array(FFT / 2), edges).every((b) => b === 0)).toBe(true);
    expect(toBands(new Uint8Array(FFT / 2).fill(255), edges).every((b) => b === 1)).toBe(true);
  });
});

describe("LightLevels", () => {
  // a band at `db` dBFS, as toBands gives it (0-1 over MIN_DB..MAX_DB)
  const at = (db: number) => (db - MIN_DB) / (MAX_DB - MIN_DB);
  // music's usual slope: each octave up ~4.5 dB quieter than the one below
  const pink = (loudest: number) => bandCentres().map((hz) => at(loudest - TILT_DB_PER_OCTAVE * Math.log2(hz / LOW_HZ)));
  const settle = (l: LightLevels, bands: number[], frames = 60) => {
    let out: number[] = [];
    for (let i = 0; i < frames; i++) out = l.apply(bands);
    return out;
  };

  it("music's slope comes out even: the treble as bright as the bass", () => {
    const out = settle(new LightLevels(), pink(-20));
    const spread = Math.max(...out) - Math.min(...out);
    expect(spread).toBeLessThan(0.05);
    expect(Math.min(...out)).toBeGreaterThan(0.9);
  });

  it("silence is dark, whatever the tilt adds up high", () => {
    const out = settle(new LightLevels(), Array<number>(BANDS).fill(0));
    expect(out.every((v) => v === 0)).toBe(true);
  });

  it("a passage 20 dB quieter goes most of the way dark, not just a third", () => {
    const l = new LightLevels();
    settle(l, pink(-20));
    const quiet = settle(l, pink(-40), 3); // right after: the peak hasn't fallen yet
    expect(Math.max(...quiet)).toBeLessThan(0.25);
    expect(Math.max(...quiet)).toBeGreaterThan(0);
  });

  it(`${WINDOW_DB} dB below the peak and further is dark`, () => {
    const l = new LightLevels();
    settle(l, pink(-20));
    expect(Math.max(...settle(l, pink(-20 - WINDOW_DB - 1), 3))).toBe(0);
  });

  it("a quieter song still moves the lights: the peak follows it down", () => {
    const l = new LightLevels();
    settle(l, pink(-20));
    const later = settle(l, pink(-28), 30 * 10); // 10 s of a song 8 dB quieter
    expect(Math.min(...later)).toBeGreaterThan(0.9);
  });

  it("near-silence isn't blown up into light", () => {
    const out = settle(new LightLevels(), pink(-80), 30 * 30);
    expect(Math.max(...out)).toBe(0);
  });

  it("always 0-1, one value per band", () => {
    const out = new LightLevels().apply(Array<number>(BANDS).fill(1));
    expect(out).toHaveLength(BANDS);
    expect(out.every((v) => v >= 0 && v <= 1)).toBe(true);
  });
});

describe("BeatDetector", () => {
  const frames = (seconds: number) => Array.from({ length: Math.round(seconds * 30) }, (_, i) => i / 30);
  const DB = MAX_DB - MIN_DB;
  // the bass at `low` dBFS over a steady rest of the song, as toBands gives it
  const bands = (low: number) => [...Array<number>(5).fill((low - MIN_DB) / DB), ...Array<number>(27).fill(0.5)];

  it("finds the kicks of a 120 BPM song: the bass jumps a few dB", () => {
    const d = new BeatDetector();
    const beats = frames(10).filter((t) => {
      const kick = t % 0.5 < 0.07; // 2 kicks a second, ~2 frames each
      return d.push(bands(kick ? -24 : -30), t); // +6 dB: values 0.73 -> 0.80, far from 1.4x
    });
    expect(beats.length).toBeGreaterThanOrEqual(18); // ~20 in 10 s
    expect(beats.length).toBeLessThanOrEqual(21);
    for (let i = 1; i < beats.length; i++) expect((beats[i] ?? 0) - (beats[i - 1] ?? 0)).toBeGreaterThanOrEqual(GAP);
  });

  it("finds none in a steady sound that wobbles a little", () => {
    let seed = 1;
    const random = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const d = new BeatDetector();
    const wobble = MIN_FLUX_DB / DB; // never a rise of MIN_FLUX_DB on average
    const beats = frames(20).filter((t) => d.push(Array.from({ length: 32 }, () => 0.6 + (random() - 0.5) * wobble), t));
    expect(beats).toEqual([]);
  });

  it("finds none in silence, nor in a held bass note", () => {
    const d = new BeatDetector();
    expect(frames(5).filter((t) => d.push(bands(-100), t))).toEqual([]);
    expect(frames(5).filter((t) => d.push(bands(-20), t)).length).toBeLessThanOrEqual(1); // its start, at most
  });

  it("a small rise is no kick", () => {
    const d = new BeatDetector();
    const beats = frames(10).filter((t) => d.push(bands(t % 0.5 < 0.07 ? -28 : -30), t)); // +2 dB
    expect(beats).toEqual([]);
  });

  it(`never more often than every ${GAP} s, even with a kick every 4th frame`, () => {
    const d = new BeatDetector();
    const beats = frames(3).filter((t, i) => d.push(bands(i % 4 === 0 ? -15 : -40), t)); // 7.5 a second
    expect(beats.length).toBeGreaterThan(3);
    for (let i = 1; i < beats.length; i++) expect((beats[i] ?? 0) - (beats[i - 1] ?? 0)).toBeGreaterThanOrEqual(GAP);
  });
});
