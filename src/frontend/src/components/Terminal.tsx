// The fake terminal (tech-spec 4.5; plan step 3): the backend's log lines as
//
//   [14:02:17.481] rgb-core    INFO  frame 008412 committed
//
// a colour per level and per tag, the last 300 lines, the newest at the
// bottom. Text is always rendered as text: board output ends up here.
import { memo } from "react";

import type { LogLine } from "../api/messages";
import { LOG_LINES } from "../api/store";
import { useStand } from "../api/useStand";

export const BANNER = [
  " ___    ___   ___     ___   __   ___   __ ",
  "|   \\  / _ \\ |   \\   |_  ) /  \\ |_  ) / / ",
  "| |) || (_) || |) |   / / | () | / / / _ \\",
  "|___/  \\___/ |___/   /___| \\__/ /___|\\___/",
  "        LIGHT ENGINE v4.2.0 · build 1816",
].join("\n");

const TAG_COLOURS = ["hot", "warm", "cool", "ok", "vio"] as const;
const TAG_WIDTH = 11;
const LEVEL_WIDTH = 6;

/** The same colour for a tag everywhere, every time (a sum of its characters). */
export function tagColour(tag: string): (typeof TAG_COLOURS)[number] {
  let sum = 0;
  for (const c of tag) sum += c.charCodeAt(0);
  return TAG_COLOURS[sum % TAG_COLOURS.length] ?? "cool";
}

/** [HH:MM:SS.mmm] of a line's time (seconds), in the notebook's local time. */
export function timestamp(t: number): string {
  const d = new Date(t * 1000);
  const two = (n: number) => String(n).padStart(2, "0");
  return `[${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}.${String(d.getMilliseconds()).padStart(3, "0")}]`;
}

type Line = LogLine & { id?: number };

const Row = memo(function Row({ line }: { line: Line }) {
  return (
    <div className="ln" data-testid="line">
      <span className="ts">{timestamp(line.t)} </span>
      <span className={`tg tg-${tagColour(line.tag)}`}>{line.tag.padEnd(TAG_WIDTH)}</span>
      <span className={`lv lv-${line.level}`}>{line.level.padEnd(LEVEL_WIDTH)}</span>
      <span className="msg">{line.text}</span>
    </div>
  );
});

export function Terminal({ lines, title = "dod-engine — tty0" }: { lines: readonly Line[]; title?: string }) {
  const shown = lines.length > LOG_LINES ? lines.slice(-LOG_LINES) : lines;
  const first = lines.length - shown.length;
  return (
    <section className="term" aria-label="Terminál">
      <div className="term-head" aria-hidden="true">
        <i />
        <i />
        <i />
        <span>{title}</span>
      </div>
      <div className="term-body">
        <div className="banner" aria-hidden="true">
          {BANNER}
        </div>
        {shown.map((line, i) => (
          <Row key={line.id ?? first + i} line={line} />
        ))}
        <div>
          <span className="cur" />
        </div>
      </div>
    </section>
  );
}

export function LiveTerminal() {
  const lines = useStand((s) => s.log);
  return <Terminal lines={lines} />;
}
