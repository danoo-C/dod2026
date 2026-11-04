// The main screen plays the songs (tech-spec 5.2; backend.md 6; plan step 7).
//
// - one <video> for good (a media element connects to Web Audio only once);
//   when `state.music.song` changes it plays /media/<id>.mp4, from where the
//   song is now if it already runs (a reload), and stops when it goes null
// - `player` messages: the position once a second, and `ended: true` when the
//   video ends or can't play – the backend ends the song either way after
//   10 s, this only makes it quicker
// - the spectrum ~30 times a second while the video plays and the page is
//   visible: 32 bands and a beat flag (spectrum.ts, beat.ts)
import { useEffect, useRef } from "react";

import { useServerClock, useStand, useStandActions } from "../../api/useStand";
import { connectAnalyser, type Analyser } from "./audioGraph";
import { BeatDetector } from "./beat";
import { AutoGain, bandEdges, toBands } from "./spectrum";

export const POSITION_MS = 1000;
export const SPECTRUM_MS = 1000 / 30;

export function Player({ visible }: { visible: boolean }) {
  const song = useStand((s) => s.state?.music.song ?? null);
  const title = useStand((s) => s.state?.music.title ?? s.state?.music.song ?? "");
  const startedAt = useStand((s) => s.state?.music.started_at ?? null);
  const startedRef = useRef(startedAt); // read when the song changes, not an effect's dependency
  startedRef.current = startedAt;
  const { send } = useStandActions();
  const clock = useServerClock();
  const video = useRef<HTMLVideoElement>(null);
  const current = useRef<string | null>(null); // the song the video has
  const sendRef = useRef(send);
  sendRef.current = send;

  // a new song: load it, from where it is now (a reload in the middle of a song)
  useEffect(() => {
    const v = video.current;
    if (v === null || song === current.current) return;
    current.current = song;
    if (song === null) {
      v.pause();
      v.removeAttribute("src");
      v.load();
      return;
    }
    v.src = `/media/${song}.mp4`;
    const started = startedRef.current;
    const elapsed = started === null ? 0 : clock.now() - started;
    if (elapsed > 1) v.currentTime = elapsed;
    connectAnalyser(v)?.resume();
    v.play()?.catch((e: unknown) => {
      console.warn("dod: the song can't play", e);
      sendRef.current({ type: "player", song, position: 0, ended: true });
    });
  }, [song, clock]);

  // the end, or a video that can't play
  useEffect(() => {
    const v = video.current;
    if (v === null) return;
    const ended = () => {
      if (current.current !== null) {
        sendRef.current({ type: "player", song: current.current, position: v.currentTime || 0, ended: true });
      }
    };
    v.addEventListener("ended", ended);
    v.addEventListener("error", ended);
    return () => {
      v.removeEventListener("ended", ended);
      v.removeEventListener("error", ended);
    };
  }, []);

  // the position, once a second while a song is loaded
  useEffect(() => {
    if (song === null) return;
    const id = setInterval(() => {
      const v = video.current;
      if (v !== null && !v.ended) sendRef.current({ type: "player", song, position: v.currentTime || 0, ended: false });
    }, POSITION_MS);
    return () => clearInterval(id);
  }, [song]);

  // the spectrum, while the video plays and the page is visible
  useEffect(() => {
    if (song === null) return;
    const v = video.current;
    const analyser: Analyser | null = v === null ? null : connectAnalyser(v);
    if (analyser === null) return;
    const edges = bandEdges(analyser.sampleRate, analyser.fftSize);
    const bins = new Uint8Array(analyser.fftSize / 2);
    const gain = new AutoGain();
    const beats = new BeatDetector();
    let last = -Infinity;
    let frame = 0;
    const step = (now: number) => {
      frame = requestAnimationFrame(step);
      if (document.hidden || v === null || v.paused || now - last < SPECTRUM_MS - 2) return;
      last = now;
      analyser.read(bins);
      const bands = gain.apply(toBands(bins, edges));
      sendRef.current({ type: "spectrum", bands, beat: beats.push(bands, now / 1000) });
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [song]);

  // always in the page (the <video> must stay), hidden while no song plays
  return (
    <div className="video" data-testid="video" hidden={!visible}>
      <video ref={video} playsInline preload="auto" />
      <div className="video-meta">
        <span className="chip">VIDEO</span>
        <h2>{title}</h2>
      </div>
    </div>
  );
}
