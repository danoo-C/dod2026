// `/` on a visitor's phone (tech-spec 4.6, 5.1; plan step 5). The phone is
// only a remote: it never plays video or audio. Which screen it shows comes
// from `you` (phoneScreen.ts); everything it shows comes from the state.
import { useState } from "react";

import type { PresetInfo, QueuePart, SongInfo } from "../api/messages";
import { useServerClock, useStand, useStandActions } from "../api/useStand";
import { Drawing } from "../apps/Manual/Drawing";
import { Params } from "../apps/Manual/Params";
import { Presets } from "../apps/Manual/Presets";
import { SongList } from "../apps/Music/SongList";
import { Countdown, useTick } from "../components/Countdown";
import { LoadingScreen } from "../components/LoadingScreen";
import { LivePreview, LiveStrip } from "../components/Preview";
import { LiveToast } from "../components/Toast";
import { minutes, people } from "../lib/slovak";
import "../styles/phone.css";
import { usePhoneScreen, waitSeconds } from "./phoneScreen";

const QUEUE_DOTS = 7; // more than this in the queue line: "+N"
// fallbacks for useStand(): a new [] on every read would make React render forever
const NO_PRESETS: PresetInfo[] = [];
const NO_SONGS: SongInfo[] = [];

export function Phone() {
  const you = useStand((s) => s.you);
  const { screen, loaded } = usePhoneScreen(you);
  return (
    <div className="phone">
      <header className="ph-top">
        <span className="logo">
          DOD<em>·</em>26
        </span>
        <LiveStrip />
      </header>
      {screen === "connecting" && <Connecting />}
      {screen === "welcome" && <Welcome />}
      {screen === "waiting" && <Waiting />}
      {screen === "loading" && (
        <div className="scr">
          <LoadingScreen title="Pripravujem tvoj ťah…" onDone={loaded} />
        </div>
      )}
      {screen === "control" && <Control />}
      {screen === "ended" && <Ended />}
      <LiveToast />
    </div>
  );
}

function Connecting() {
  return (
    <div className="scr center">
      <p className="note">Pripájam sa k stánku…</p>
    </div>
  );
}

// --- not in the queue ---------------------------------------------------------

function Welcome() {
  const waiting = useStand((s) => s.state?.queue.waiting ?? 0);
  const turn = useStand((s) => s.welcome?.turn_seconds ?? 180);
  const { send } = useStandActions();
  return (
    <div className="scr">
      <div className="hero">
        <h2>Ovládaj svetlá na stánku</h2>
        <p>
          Postav sa do radu. Keď prídeš na rad, máš {minutes(Math.round(turn / 60))} na presety, kreslenie na 8×8
          a hudbu.
        </p>
      </div>
      <div className="card">
        <h4>Práve na stánku</h4>
        <LivePreview size="phone" />
        <p className="note">V rade {waiting === 0 ? "nikto nečaká" : `čaká ${people(waiting)}`}.</p>
      </div>
      <button type="button" className="wide-btn primary" onClick={() => send({ type: "join_queue" })}>
        Postaviť sa do radu
      </button>
    </div>
  );
}

function Ended() {
  const waiting = useStand((s) => s.state?.queue.waiting ?? 0);
  const { send } = useStandActions();
  return (
    <div className="scr">
      <div className="end">
        <span className="face" aria-hidden="true">
          :(
        </span>
        <h3>Tvoj čas skončil</h3>
        <p>
          {waiting > 0
            ? "Ďalší v rade už čaká. Môžeš sa postaviť znova na koniec radu."
            : "Môžeš sa postaviť do radu znova."}
        </p>
        <button type="button" className="wide-btn primary" onClick={() => send({ type: "join_queue" })}>
          Znova do radu
        </button>
      </div>
    </div>
  );
}

// --- waiting ------------------------------------------------------------------

function waitText(seconds: number): string {
  if (seconds <= 30) return "Si na rade o chvíľu";
  return `Na rade si približne o ${minutes(Math.ceil(seconds / 60))}`;
}

function QueueLine({ position, queue }: { position: number; queue: QueuePart }) {
  const total = Math.max(queue.waiting, position);
  const shown = Math.min(total, QUEUE_DOTS);
  // everyone ahead of you is a dot, you are "ty"; nobody's id is shown (backend.md 9)
  const chips = Array.from({ length: shown }, (_, i) => i + 1);
  if (position > shown) chips[shown - 1] = position;
  return (
    <div className="qline" aria-label={`Rad: si ${position}. z ${total}`}>
      {queue.controller !== null && <span>hrá teraz</span>}
      {chips.map((n) => (
        <span key={n} className={n === position ? "me" : undefined}>
          {n === position ? "ty" : "·"}
        </span>
      ))}
      {total > shown && <span>+{total - shown}</span>}
    </div>
  );
}

function Waiting() {
  const position = useStand((s) => s.you?.position ?? 1);
  const queue = useStand((s) => s.state?.queue ?? null);
  const turn = useStand((s) => s.welcome?.turn_seconds ?? 180);
  const playing = useStand((s) => (s.state?.music.playing ? s.state.music.title : null));
  const clock = useServerClock();
  const { send } = useStandActions();
  useTick(1000);
  return (
    <div className="scr">
      <div className="pos">
        <span className="num">{position}.</span>
        <h3>Si v poradí</h3>
        <p data-testid="wait">
          {queue?.paused ? "Rad je na chvíľu pozastavený" : queue === null ? "…" : waitText(waitSeconds(position, queue, turn, clock))}
        </p>
      </div>
      {queue !== null && <QueueLine position={position} queue={queue} />}
      <div className="card">
        <h4>Práve na stánku</h4>
        <LivePreview size="phone" />
        {playing !== null && <p className="note">Hrá: {playing}</p>}
      </div>
      <button type="button" className="wide-btn quiet" onClick={() => send({ type: "leave_queue" })}>
        Odísť z radu
      </button>
    </div>
  );
}

// --- in control ---------------------------------------------------------------

type Tab = "manual" | "music";

function Control() {
  const [tab, setTab] = useState<Tab>("manual");
  const [songLoading, setSongLoading] = useState(false);
  const { send } = useStandActions();

  if (songLoading) {
    return (
      <div className="scr">
        <LoadingScreen title="Pripravujem skladbu…" onDone={() => setSongLoading(false)} />
      </div>
    );
  }
  return (
    <div className="scr">
      <TurnTimer />
      <div className="tabs" role="tablist" aria-label="Režim">
        <button type="button" role="tab" aria-selected={tab === "manual"} onClick={() => setTab("manual")}>
          Ovládanie
        </button>
        <button type="button" role="tab" aria-selected={tab === "music"} onClick={() => setTab("music")}>
          Hudba
        </button>
      </div>
      {tab === "manual" ? (
        <Manual />
      ) : (
        <Music
          onPick={(song) => {
            if (send({ type: "play_song", song })) setSongLoading(true);
          }}
        />
      )}
    </div>
  );
}

function TurnTimer() {
  const ends = useStand((s) => s.you?.turn_ends_at ?? null);
  const turn = useStand((s) => s.welcome?.turn_seconds ?? 180);
  // time is up, but nobody waits: the turn simply goes on (tech-spec 4.6)
  const open = useStand((s) => (s.state?.queue.turn_over ?? false) && (s.state?.queue.waiting ?? 0) === 0);
  return (
    <div className="turn">
      {open ? (
        <div className="timer">
          <b className="countdown" data-testid="countdown">
            ∞
          </b>
        </div>
      ) : (
        <Countdown to={ends} total={turn} />
      )}
      <div>
        <h3>Tvoj ťah!</h3>
        <p>{open ? "Kým niekto nepríde" : "Ovládaš svetlá na stánku"}</p>
      </div>
    </div>
  );
}

function Manual() {
  const presets = useStand((s) => s.welcome?.presets ?? NO_PRESETS);
  const manual = useStand((s) => s.state?.manual ?? null);
  const { send } = useStandActions();
  const current = presets.find((p) => p.id === manual?.preset) ?? null;
  return (
    <>
      <div className="card">
        <h4>Preset</h4>
        <Presets presets={presets} current={manual?.preset ?? null} onPick={(preset) => send({ type: "set_preset", preset })} />
      </div>
      {current !== null && manual !== null && (
        <div className="card">
          <h4>Nastavenia · {current.name}</h4>
          {/* keyed by the preset: its controls start fresh, the old ones send their last value */}
          <Params
            key={current.id}
            params={current.params}
            values={manual.params}
            onChange={(name, value) => send({ type: "set_param", name, value })}
          />
        </div>
      )}
      {manual !== null && (
        <div className="card">
          <h4>Kresli na 8×8</h4>
          <Drawing
            drawing={manual.drawing}
            showing={manual.matrix === "drawing"}
            onDraw={(drawing) => send({ type: "set_matrix", mode: "drawing", drawing })}
            onIcon={() => send({ type: "set_matrix", mode: "icon" })}
          />
        </div>
      )}
    </>
  );
}

function Music({ onPick }: { onPick(song: string): void }) {
  const songs = useStand((s) => s.welcome?.songs ?? NO_SONGS);
  const music = useStand((s) => s.state?.music ?? null);
  return <SongList songs={songs} music={music} onPick={onPick} />;
}
