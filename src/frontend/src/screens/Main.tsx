// /internal/main, the notebook's screen (tech-spec 5.1; plan step 6):
//
//   ┌ terminal ┬──────────── right part ─────────────┐
//   │ (25-33 %)│ a song: its video (Player)          │
//   │          │ otherwise: big QR codes, the queue, │
//   │          │ the large preview                   │
//   │          ├──────────── info bar ───────────────┤
//   │          │ what plays · preview · queue · QR   │
//   └──────────┴─────────────────────────────────────┘
//
// It only connects after "Spustiť" (StartGate): the browser allows audio
// after a click, and until then it isn't the stand's player.
import { useCallback, useState, type CSSProperties, type ReactNode } from "react";

import { useServerClock, useStand } from "../api/useStand";
import { AdminPanel, TERM_MAX, TERM_MIN, useAdminShortcut, useKickShortcut } from "../components/AdminPanel";
import { primeAudio } from "../apps/Music/audioGraph";
import { Player } from "../apps/Music/Player";
import { LiveBadge } from "../components/Badge";
import { useTick } from "../components/Countdown";
import { LivePreview } from "../components/Preview";
import { Qr, wifiQr } from "../components/Qr";
import { LiveTerminal } from "../components/Terminal";
import { LiveToast } from "../components/Toast";
import { formatSeconds } from "../api/clock";
import { people } from "../lib/slovak";
import "../styles/main.css";

const TERM_KEY = "dod.termWidth";
const TERM_DEFAULT = 30;

/** "Spustiť" once, then the screen (and its connection). */
export function StartGate({ children }: { children: ReactNode }) {
  const [started, setStarted] = useState(false);
  if (started) return <>{children}</>;
  return (
    <div className="start">
      <h1>DOD 2026 · Svetelná show</h1>
      <p>Klikni raz, aby prehliadač dovolil zvuk. Potom sa obrazovka pripojí k stánku.</p>
      <button
        type="button"
        className="start-btn"
        autoFocus
        onClick={() => {
          primeAudio(); // in the click itself: the browser allows sound now
          setStarted(true);
        }}
      >
        Spustiť
      </button>
    </div>
  );
}

function clampWidth(n: number): number {
  return Number.isFinite(n) ? Math.min(TERM_MAX, Math.max(TERM_MIN, Math.round(n))) : TERM_DEFAULT;
}

/** The terminal's width in %, remembered in this browser. */
function useTermWidth(): [number, (n: number) => void] {
  const [width, setWidth] = useState(() => {
    try {
      const saved = window.localStorage.getItem(TERM_KEY);
      return saved === null ? TERM_DEFAULT : clampWidth(Number(saved));
    } catch {
      return TERM_DEFAULT;
    }
  });
  const set = useCallback((n: number) => {
    const w = clampWidth(n);
    setWidth(w);
    try {
      window.localStorage.setItem(TERM_KEY, String(w));
    } catch {
      // private mode: the width just isn't remembered
    }
  }, []);
  return [width, set];
}

export function Main() {
  const [termWidth, setTermWidth] = useTermWidth();
  const [admin, setAdmin] = useState(false);
  const close = useCallback(() => setAdmin(false), []);
  useAdminShortcut(() => setAdmin(true));
  useKickShortcut();
  const music = useStand((s) => s.state?.mode === "music");
  return (
    <div className="nb" style={{ "--term-w": `${termWidth}%` } as CSSProperties}>
      <LiveTerminal />
      <div className="stage">
        <Player visible={music} />
        {!music && <Attract />}
        <InfoBar qr={music} />
      </div>
      {admin && <AdminPanel onClose={close} termWidth={termWidth} setTermWidth={setTermWidth} />}
      <LiveToast />
    </div>
  );
}

// --- the right part -----------------------------------------------------------

function QrCodes({ size }: { size: number | string }) {
  const url = useStand((s) => s.welcome?.public_url ?? null);
  const wifi = useStand((s) => s.welcome?.wifi ?? null);
  if (url === null) return null;
  return (
    <div className="qrs">
      {wifi !== null && <Qr value={wifiQr(wifi.ssid, wifi.password)} label="1. Wi-Fi" size={size} />}
      <Qr value={url} label={wifi !== null ? "2. Stránka" : "Stránka"} size={size} />
    </div>
  );
}

/** No song: the big QR codes, the queue, the large preview – the stand inviting people. */
function Attract() {
  const wifi = useStand((s) => s.welcome?.wifi ?? null);
  const waiting = useStand((s) => s.state?.queue.waiting ?? 0);
  const playing = useStand((s) => s.state?.queue.controller != null);
  return (
    <div className="idle" data-testid="attract">
      <div>
        <h2>Naskenuj kód a ovládaj svetlá</h2>
        <p>
          {wifi !== null
            ? `Pripoj sa na Wi-Fi ${wifi.ssid}, otvor stránku a postav sa do radu.`
            : "Otvor stránku v mobile a postav sa do radu."}
        </p>
        <p className="idle-queue">
          {waiting > 0 ? `V rade čaká ${people(waiting)}.` : playing ? "Nikto nečaká, si hneď ďalší." : "Nikto nehrá, si hneď na rade."}
        </p>
        <LivePreview size="large" />
      </div>
      <QrCodes size="clamp(110px, 13vw, 190px)" />
    </div>
  );
}

// --- the info bar -------------------------------------------------------------

function NowPlaying() {
  const mode = useStand((s) => s.state?.mode ?? "idle");
  const music = useStand((s) => s.state?.music ?? null);
  const preset = useStand((s) => {
    const id = s.state?.manual.preset;
    return s.welcome?.presets.find((p) => p.id === id)?.name ?? id ?? "";
  });
  const drawing = useStand((s) => s.state?.manual.matrix === "drawing");
  const clock = useServerClock();
  useTick(1000);

  if (mode === "music" && music !== null) {
    const length = music.length ?? 0;
    const elapsed = music.started_at === null ? 0 : Math.max(0, Math.min(length || Infinity, clock.now() - music.started_at));
    return (
      <div className="np">
        <span className="lbl">Práve hrá</span>
        <b>{music.title ?? music.song}</b>
        <div className="prog">
          <i style={{ width: length > 0 ? `${(elapsed / length) * 100}%` : "0%" }} />
        </div>
        <span className="time" data-testid="song-time">
          {formatSeconds(elapsed)} / {length > 0 ? formatSeconds(length) : "–:––"}
        </span>
      </div>
    );
  }
  return (
    <div className="np">
      <span className="lbl">{mode === "manual" ? "Ručné ovládanie" : "Pokoj"}</span>
      <b>{mode === "manual" ? `Preset: ${preset}${drawing ? " · kresba na 8×8" : ""}` : "Nič nehrá"}</b>
    </div>
  );
}

function InfoBar({ qr }: { qr: boolean }) {
  const waiting = useStand((s) => s.state?.queue.waiting ?? 0);
  return (
    <div className="bar">
      <NowPlaying />
      <LivePreview />
      <div className="q">
        <span className="lbl">V rade</span>
        <b className="big">{waiting}</b>
      </div>
      {qr && <QrCodes size={64} />}
      <LiveBadge />
    </div>
  );
}
