// The strip and the 8x8 as the board shows them, from `preview` messages
// (backend.md 9; plan step 3): the strip as "#rrggbb" per LED (before gamma,
// as a person sees it), the 8x8 as 16 hex characters – 8 rows, row 0 on
// top, bit 7 the leftmost pixel – in the LEDs' red, dimmed by its brightness.
import type { CSSProperties } from "react";

import type { Preview as PreviewMessage } from "../api/messages";
import { useStand } from "../api/useStand";

export const MATRIX_SIZE = 8;
const MAX_BRIGHTNESS = 15; // the MAX7219's steps
const PLACEHOLDER_LEDS = 10; // before the first preview: the strip's usual length, all off
const DARK = 18; // r + g + b below this shows as an LED that is off

export type PreviewSize = "small" | "large" | "phone";

/** The 64 pixels, row by row, left to right; anything malformed is all off. */
export function decodeMatrix(hex: string): boolean[] {
  if (!/^[0-9a-fA-F]{16}$/.test(hex)) return Array<boolean>(MATRIX_SIZE * MATRIX_SIZE).fill(false);
  const pixels: boolean[] = [];
  for (let row = 0; row < MATRIX_SIZE; row++) {
    const bits = parseInt(hex.slice(row * 2, row * 2 + 2), 16);
    for (let x = 0; x < MATRIX_SIZE; x++) pixels.push((bits & (0x80 >> x)) !== 0);
  }
  return pixels;
}

/** The matrix's brightness, 0-15, as 0-1. */
export function matrixLevel(brightness: number): number {
  return Math.max(0, Math.min(1, brightness / MAX_BRIGHTNESS));
}

function ledStyle(color: string): CSSProperties | undefined {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color);
  if (m === null) return undefined;
  const [r, g, b] = [m[1], m[2], m[3]].map((h) => parseInt(h ?? "0", 16)) as [number, number, number];
  if (r + g + b < DARK) return undefined; // looks off
  return { background: color, boxShadow: `0 0 10px rgb(${r} ${g} ${b} / 0.75)` };
}

export function Strip({ leds }: { leds: readonly string[] }) {
  return (
    <div className="strip" role="img" aria-label={`Pásik, ${leds.length} LED`}>
      {leds.map((color, i) => (
        <span key={i} className="led" data-testid="led" style={ledStyle(color)} />
      ))}
    </div>
  );
}

export function Matrix({ hex, brightness }: { hex: string; brightness: number }) {
  const pixels = decodeMatrix(hex);
  const style = { "--level": matrixLevel(brightness) } as CSSProperties;
  return (
    <div className="matrix" role="img" aria-label="Mriežka 8×8" style={style} data-testid="matrix">
      {pixels.map((on, i) => (
        <span key={i} className={on ? "px on" : "px"} />
      ))}
    </div>
  );
}

export function Preview({ preview, size = "small" }: { preview: PreviewMessage | null; size?: PreviewSize }) {
  const leds = preview?.leds ?? Array<string>(PLACEHOLDER_LEDS).fill("#000000");
  return (
    <div className={`pv ${size}`}>
      <Strip leds={leds} />
      <Matrix hex={preview?.matrix ?? "0000000000000000"} brightness={preview?.brightness ?? 0} />
    </div>
  );
}

/** The stand's preview, live: re-renders 10 times a second, so keep it small and leaf-like. */
export function LivePreview({ size }: { size?: PreviewSize }) {
  const preview = useStand((s) => s.preview);
  return <Preview preview={preview} size={size} />;
}

/** Only the strip (the phone's header). */
export function LiveStrip() {
  const leds = useStand((s) => s.preview?.leds) ?? Array<string>(PLACEHOLDER_LEDS).fill("#000000");
  return <Strip leds={leds} />;
}
