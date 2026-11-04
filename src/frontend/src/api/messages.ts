/* Generated from src/backend/schema/messages.json by scripts/types.mjs.
 * Do not edit: change the models in src/backend/dod/api/messages.py and run ./dod schema. */

/**
 * incoming: browser -> server, outgoing: server -> browser (docs/backend.md 9)
 */
export interface Messages {
  incoming:
    JoinQueue | LeaveQueue | SetPreset | SetParam | SetMatrix | PlaySong | LoadingStarted | Spectrum | Player | Admin;
  outgoing: Welcome | StateMessage | You | Preview | Log | Error;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "JoinQueue".
 */
export interface JoinQueue {
  type: "join_queue";
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "LeaveQueue".
 */
export interface LeaveQueue {
  type: "leave_queue";
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "SetPreset".
 */
export interface SetPreset {
  type: "set_preset";
  preset: string;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "SetParam".
 */
export interface SetParam {
  type: "set_param";
  name: string;
  value: boolean | number | string;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "SetMatrix".
 */
export interface SetMatrix {
  type: "set_matrix";
  mode: "icon" | "drawing";
  drawing?: string | null;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "PlaySong".
 */
export interface PlaySong {
  type: "play_song";
  song: string;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "LoadingStarted".
 */
export interface LoadingStarted {
  type: "loading_started";
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "Spectrum".
 */
export interface Spectrum {
  type: "spectrum";
  bands: number[];
  beat?: boolean;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "Player".
 */
export interface Player {
  type: "player";
  song: string;
  position: number;
  ended?: boolean;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "Admin".
 */
export interface Admin {
  type: "admin";
  action: "skip" | "pause_queue" | "resume_queue" | "stop_song";
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "Welcome".
 */
export interface Welcome {
  type: "welcome";
  role: "phone" | "main" | "logging";
  session: string | null;
  presets: PresetInfo[];
  songs: SongInfo[];
  public_url: string;
  turn_seconds: number;
  inactive_seconds: number;
  wifi: WifiInfo | null;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "PresetInfo".
 */
export interface PresetInfo {
  id: string;
  name: string;
  params: ParamInfo[];
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "ParamInfo".
 */
export interface ParamInfo {
  name: string;
  label: string;
  kind: "slider" | "color" | "choice" | "toggle";
  default: boolean | number | string;
  min: number | null;
  max: number | null;
  step: number | null;
  options: OptionInfo[] | null;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "OptionInfo".
 */
export interface OptionInfo {
  value: string;
  label: string;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "SongInfo".
 */
export interface SongInfo {
  id: string;
  title: string;
  length: number | null;
  ready: boolean;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "WifiInfo".
 */
export interface WifiInfo {
  ssid: string;
  password: string;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "StateMessage".
 */
export interface StateMessage {
  type: "state";
  now: number;
  mode: "manual" | "music" | "idle";
  manual: ManualPart;
  music: MusicPart;
  queue: QueuePart;
  hardware: HardwarePart;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "ManualPart".
 */
export interface ManualPart {
  preset: string;
  params: {
    [k: string]: boolean | number | string;
  };
  matrix: "icon" | "drawing";
  drawing: string;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "MusicPart".
 */
export interface MusicPart {
  song: string | null;
  title: string | null;
  started_at: number | null;
  length: number | null;
  playing: boolean;
  player_connected: boolean;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "QueuePart".
 */
export interface QueuePart {
  controller: string | null;
  turn_ends_at: number | null;
  turn_over: boolean;
  waiting: number;
  paused: boolean;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "HardwarePart".
 */
export interface HardwarePart {
  state: string;
  simulated: boolean;
  fps: number;
  error: string | null;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "You".
 */
export interface You {
  type: "you";
  session: string | null;
  position: number | null;
  in_control: boolean;
  turn_ends_at: number | null;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "Preview".
 */
export interface Preview {
  type: "preview";
  leds: string[];
  matrix: string;
  brightness: number;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "Log".
 */
export interface Log {
  type: "log";
  lines: LogLine[];
}
/**
 * One line of the fake terminal (docs/backend.md 10); the page does the colours.
 *
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "LogLine".
 */
export interface LogLine {
  t: number;
  tag: string;
  level: "DEBUG" | "INFO" | "OK" | "WARN";
  text: string;
}
/**
 * This interface was referenced by `Messages`'s JSON-Schema
 * via the `definition` "Error".
 */
export interface Error {
  type: "error";
  code: "invalid" | "forbidden" | "not_your_turn" | "no_player" | "unknown_song" | "rate_limited";
  message: string;
}

/** Browser -> server. */
export type Incoming = Messages["incoming"];
/** Server -> browser. */
export type Outgoing = Messages["outgoing"];
