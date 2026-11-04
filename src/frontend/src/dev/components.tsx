// The components page (dev only, plan step 3): every shared component with
// fake data that moves, so they can be checked by eye without a backend.
import { StrictMode, useEffect, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import type { HardwarePart, LogLine, Preview as PreviewMessage } from "../api/messages";
import type { Status } from "../api/socket";
import { Badge } from "../components/Badge";
import { Countdown } from "../components/Countdown";
import { LoadingScreen } from "../components/LoadingScreen";
import { Preview } from "../components/Preview";
import { Qr, wifiQr } from "../components/Qr";
import { Terminal } from "../components/Terminal";
import "../styles/tokens.css";
import "../styles/components.css";

const LEDS = 10;

function hsl(h: number): string {
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    const c = 0.5 - 0.5 * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(255 * c).toString(16).padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

/** A rainbow with a beating heart on the 8x8, 10 frames a second, like real previews. */
function useFakePreview(): PreviewMessage {
  const [t, setT] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setT((n) => n + 1), 100);
    return () => clearInterval(id);
  }, []);
  const heart = ["00000000", "01100110", "11111111", "11111111", "01111110", "00111100", "00011000", "00000000"];
  const matrix = heart.map((r) => parseInt(r, 2).toString(16).padStart(2, "0")).join("");
  return {
    type: "preview",
    leds: Array.from({ length: LEDS }, (_, i) => (i === LEDS - 1 && t % 10 < 5 ? "#000000" : hsl(i * 36 + t * 12))),
    matrix,
    brightness: Math.round(7.5 + 7.5 * Math.sin(t / 3)),
  };
}

const TAGS = ["rgb-core", "photon-bus", "lattice", "serial", "queue", "esp32", "fft", "thermal"];
const LEVELS: LogLine["level"][] = ["INFO", "INFO", "DEBUG", "OK", "WARN"];

function useFakeLog(): LogLine[] {
  const [lines, setLines] = useState<(LogLine & { id: number })[]>([]);
  useEffect(() => {
    let n = 0;
    const id = setInterval(() => {
      n += 1;
      const line = {
        id: n,
        t: Date.now() / 1000,
        tag: TAGS[n % TAGS.length] ?? "rgb-core",
        level: LEVELS[n % LEVELS.length] ?? "INFO",
        text: n % 13 === 0 ? "<b>not bold</b> – text stays text" : `frame ${String(8400 + n).padStart(6, "0")} committed (38 B)`,
      };
      setLines((old) => [...old.slice(-299), line]);
    }, 180);
    return () => clearInterval(id);
  }, []);
  return lines;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <h2 style={{ margin: 0, font: "700 13px/1 var(--f-mono)", letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted)" }}>
        {title}
      </h2>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 18, alignItems: "flex-start" }}>{children}</div>
    </section>
  );
}

const HW: Record<string, HardwarePart> = {
  board: { state: "connected", simulated: false, fps: 29.9, error: null },
  sim: { state: "connected", simulated: true, fps: 30, error: null },
  connecting: { state: "connecting", simulated: false, fps: 0, error: null },
  lost: { state: "disconnected", simulated: false, fps: 0, error: "read timeout" },
  incompatible: { state: "incompatible", simulated: false, fps: 0, error: "protocol 2, expected 1" },
};

function Gallery() {
  const preview = useFakePreview();
  const log = useFakeLog();
  const [loading, setLoading] = useState(0);
  const [turnEnds] = useState(() => Date.now() / 1000 + 180);
  const badges: [Status, HardwarePart | null][] = [
    ["open", HW.board ?? null],
    ["open", HW.sim ?? null],
    ["open", HW.connecting ?? null],
    ["open", HW.lost ?? null],
    ["open", HW.incompatible ?? null],
    ["connecting", null],
    ["offline", null],
  ];
  return (
    <main style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 16px 60px", display: "flex", flexDirection: "column", gap: 32 }}>
      <h1 style={{ margin: 0, font: "800 28px/1 var(--f-display)" }}>Komponenty</h1>
      <Section title="Preview: small, phone, large, before the first preview">
        <Preview preview={preview} />
        <Preview preview={preview} size="phone" />
        <Preview preview={preview} size="large" />
        <Preview preview={null} />
      </Section>
      <Section title="Terminal (a line with <b> every 13th)">
        <div style={{ width: "min(100%, 520px)", height: 320, border: "1px solid var(--line)", borderRadius: 10, overflow: "hidden" }}>
          <Terminal lines={log} />
        </div>
      </Section>
      <Section title="LoadingScreen (2-4 s, then it says so)">
        <div style={{ width: 360, minHeight: 470, display: "flex", background: "var(--panel)", borderRadius: "var(--r)" }}>
          {loading >= 0 ? (
            <LoadingScreen key={loading} onDone={() => setLoading(-1)} />
          ) : (
            <button type="button" style={{ margin: "auto" }} onClick={() => setLoading(Date.now())}>
              Hotovo. Znova
            </button>
          )}
        </div>
      </Section>
      <Section title="Qr">
        <Qr value="http://192.168.137.1:8000" label="2. Stránka" size={120} />
        <Qr value={wifiQr("DOD-SPSE", "svetlo2026")} label="1. Wi-Fi" size={120} />
        <Qr value="http://192.168.137.1:8000" label="malý" />
      </Section>
      <Section title="Countdown: 3 minutes from opening this page">
        <Countdown to={turnEnds} />
        <Countdown to={turnEnds} total={180} />
        <Countdown to={null} />
      </Section>
      <Section title="Badge">
        {badges.map(([status, hw], i) => (
          <Badge key={i} status={status} hardware={hw} />
        ))}
      </Section>
    </main>
  );
}

const root = document.getElementById("root");
if (root === null) throw new Error("components.html has no #root");
createRoot(root).render(
  <StrictMode>
    <Gallery />
  </StrictMode>,
);
