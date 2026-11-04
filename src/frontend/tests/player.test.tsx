// The main screen's player (plan step 7): the <video> follows the state, the
// position and the end go to the backend, and the spectrum ~30 times a
// second. Web Audio is a fake analyser (jsdom has none).
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StateMessage } from "../src/api/messages";
import { Stand } from "../src/api/store";
import { StandProvider } from "../src/api/useStand";
import { Player } from "../src/apps/Music/Player";
import { FakeWebSocket, install, stateAt, WELCOME } from "./support/fakes";

const fakeAnalyser = {
  sampleRate: 48000,
  fftSize: 2048,
  read: vi.fn((into: Uint8Array) => into.fill(128)),
  resume: vi.fn(),
};
let audioAvailable = true;

vi.mock("../src/apps/Music/audioGraph", () => ({
  FFT_SIZE: 2048,
  connectAnalyser: () => (audioAvailable ? fakeAnalyser : null),
}));

const NOW = 1_793_711_000;
const SONG = "dQw4w9WgXcQ";

function playing(song: string | null, startedAt: number | null = NOW): StateMessage {
  const s = stateAt(NOW);
  return {
    ...s,
    mode: song === null ? "manual" : "music",
    music: { song, title: song && "Never Gonna", started_at: song === null ? null : startedAt, length: 213, playing: song !== null, player_connected: true },
  };
}

let stand: Stand;
let sent: { type: string; [k: string]: unknown }[];

async function show() {
  stand = new Stand("main");
  sent = [];
  vi.spyOn(stand, "send").mockImplementation((msg) => {
    sent.push(msg as (typeof sent)[number]);
    return true;
  });
  render(
    <StandProvider role="main" stand={stand}>
      <Player visible />
    </StandProvider>,
  );
  await act(() => vi.advanceTimersByTimeAsync(0));
  act(() => FakeWebSocket.last.accept({ ...WELCOME, role: "main" }));
}

const video = () => document.querySelector("video") as HTMLVideoElement;
const state = (s: StateMessage) => act(() => stand.store.apply(s));
const of = (type: string) => sent.filter((m) => m.type === type);

beforeEach(() => {
  vi.useFakeTimers({ now: NOW * 1000, toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance", "requestAnimationFrame", "cancelAnimationFrame"] });
  install();
  audioAvailable = true;
  fakeAnalyser.read.mockClear();
  Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("the player", () => {
  it("plays the state's song from /media, and stops when it is over", async () => {
    await show();
    const play = vi.spyOn(HTMLMediaElement.prototype, "play");
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause");
    state(playing(SONG));
    expect(video().getAttribute("src")).toBe(`/media/${SONG}.mp4`);
    expect(play).toHaveBeenCalledOnce();
    expect(fakeAnalyser.resume).toHaveBeenCalled();
    state(playing(null));
    expect(pause).toHaveBeenCalled();
    expect(video().getAttribute("src")).toBeNull();
  });

  it("a reload in the middle of a song starts where the song is", async () => {
    await show();
    state(playing(SONG, NOW - 42)); // started 42 s ago on the server's clock
    expect(video().currentTime).toBeCloseTo(42, 0);
  });

  it("the same song in a new state doesn't start it again", async () => {
    await show();
    const play = vi.spyOn(HTMLMediaElement.prototype, "play");
    state(playing(SONG));
    state({ ...playing(SONG), queue: { ...playing(SONG).queue, waiting: 3 } });
    expect(play).toHaveBeenCalledOnce();
  });

  it("the position once a second", async () => {
    await show();
    state(playing(SONG));
    video().currentTime = 12.5;
    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(of("player")).toHaveLength(3);
    expect(of("player")[0]).toEqual({ type: "player", song: SONG, position: 12.5, ended: false });
  });

  it("the end: ended, and the same when the video can't play", async () => {
    await show();
    state(playing(SONG));
    act(() => video().dispatchEvent(new Event("ended")));
    expect(of("player").at(-1)).toMatchObject({ song: SONG, ended: true });
    sent.length = 0;
    act(() => video().dispatchEvent(new Event("error")));
    expect(of("player").at(-1)).toMatchObject({ song: SONG, ended: true });
  });

  it("a song the browser refuses to play ends at once", async () => {
    await show();
    vi.spyOn(HTMLMediaElement.prototype, "play").mockRejectedValue(new DOMException("blocked", "NotAllowedError"));
    vi.spyOn(console, "warn").mockImplementation(() => {});
    state(playing(SONG));
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(of("player").at(-1)).toEqual({ type: "player", song: SONG, position: 0, ended: true });
  });
});

describe("the spectrum", () => {
  it("~30 times a second while the song plays: 32 bands and a beat flag", async () => {
    await show();
    state(playing(SONG));
    await act(() => vi.advanceTimersByTimeAsync(1000));
    const spectra = of("spectrum");
    expect(spectra.length).toBeGreaterThanOrEqual(27);
    expect(spectra.length).toBeLessThanOrEqual(31);
    const first = spectra[0] as unknown as { bands: number[]; beat: boolean };
    expect(first.bands).toHaveLength(32);
    expect(first.bands.every((b) => b >= 0 && b <= 1)).toBe(true);
    expect(typeof first.beat).toBe("boolean");
  });

  it("none while the window is hidden, none while paused, none without a song", async () => {
    await show();
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(of("spectrum")).toHaveLength(0); // no song
    state(playing(SONG));
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(of("spectrum")).toHaveLength(0);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    act(() => video().pause());
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(of("spectrum")).toHaveLength(0);
  });

  it("without Web Audio the video still plays, only without a spectrum", async () => {
    audioAvailable = false;
    await show();
    const play = vi.spyOn(HTMLMediaElement.prototype, "play");
    state(playing(SONG));
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(play).toHaveBeenCalledOnce();
    expect(of("spectrum")).toHaveLength(0);
    expect(of("player").length).toBeGreaterThan(0);
  });
});
