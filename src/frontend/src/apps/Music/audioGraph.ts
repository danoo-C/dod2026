// The Web Audio graph behind the main screen's <video> (tech-spec 5.2):
//
//   video ─▶ MediaElementSource ─▶ AnalyserNode ─▶ speakers
//
// The video comes from the same server, so the browser lets the analyser
// read it. A media element can be connected only once, so the <video> stays
// in the page for good and this runs once for it. In a module of its own so
// the tests can replace it (jsdom has no Web Audio).

import { MAX_DB, MIN_DB } from "./spectrum";

export const FFT_SIZE = 2048;

export interface Analyser {
  sampleRate: number;
  fftSize: number;
  /** The current frequency bins, 0-255 each (fftSize / 2 of them). */
  read(into: Uint8Array): void;
  /** After the "Spustiť" click the browser allows sound; a suspended context resumes. */
  resume(): void;
}

const connected = new WeakMap<HTMLMediaElement, Analyser>();
let shared: AudioContext | null = null;

function audioContext(): AudioContext | null {
  if (shared !== null) return shared;
  const Context = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (Context === undefined) return null; // no Web Audio: the video still plays, the lights just don't follow
  shared = new Context();
  return shared;
}

/**
 * In the "Spustiť" click: create the audio context and start it while the
 * click counts as the user allowing sound. Created later (when the first song
 * starts), a strict browser may leave it suspended – and a video routed
 * through a suspended context plays without sound.
 */
export function primeAudio(): void {
  void audioContext()?.resume();
}

export function connectAnalyser(video: HTMLMediaElement): Analyser | null {
  const known = connected.get(video);
  if (known !== undefined) return known;
  const context = audioContext();
  if (context === null) return null;
  let node: AnalyserNode;
  try {
    const source = context.createMediaElementSource(video);
    node = context.createAnalyser();
    node.fftSize = FFT_SIZE;
    node.minDecibels = MIN_DB; // the byte range spectrum.ts reads the bins with
    node.maxDecibels = MAX_DB;
    node.smoothingTimeConstant = 0.5; // lower: the lights follow quicker changes
    source.connect(node);
    node.connect(context.destination);
  } catch (e) {
    // the song plays on with the video's own sound; only the lights don't follow it
    console.warn("dod: no spectrum, Web Audio failed", e);
    return null;
  }
  const analyser: Analyser = {
    sampleRate: context.sampleRate,
    fftSize: node.fftSize,
    read: (into) => node.getByteFrequencyData(into as Uint8Array<ArrayBuffer>),
    resume: () => void context.resume(),
  };
  connected.set(video, analyser);
  return analyser;
}
