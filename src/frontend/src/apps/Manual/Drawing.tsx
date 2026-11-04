// Drawing on the 8x8 from the phone (tech-spec 5.3; plan step 5): tap a pixel
// to switch it, drag to paint – the first pixel decides whether the stroke
// paints or erases. Sent as `set_matrix` with `mode: "drawing"`, at most 10
// times a second, like a slider.
import { useRef, type PointerEvent } from "react";

import { decodeMatrix, EMPTY, SIZE, withPixel } from "../../lib/matrix";
import { useLocalEdit } from "../../lib/useLocalEdit";

export interface DrawingProps {
  /** The state's drawing, 16 hex characters. */
  drawing: string;
  /** Whether the 8x8 shows the drawing (or the preset's own picture). */
  showing: boolean;
  onDraw(hex: string): void;
  onIcon(): void;
}

function cellAt(x: number, y: number): number | null {
  const el = document.elementFromPoint(x, y);
  const index = el instanceof HTMLElement ? el.dataset.cell : undefined;
  return index === undefined ? null : Number(index);
}

export function Drawing({ drawing, showing, onDraw, onIcon }: DrawingProps) {
  const edit = useLocalEdit(drawing.toLowerCase(), onDraw);
  const stroke = useRef<{ paint: boolean; last: number } | null>(null);
  const pixels = decodeMatrix(edit.value);
  const current = useRef(edit.value);
  current.current = edit.value;

  const set = (index: number, on: boolean) => {
    const next = withPixel(current.current, index, on);
    if (next === current.current) return;
    current.current = next;
    edit.change(next);
  };

  const down = (e: PointerEvent<HTMLDivElement>) => {
    const index = e.target instanceof HTMLElement && e.target.dataset.cell !== undefined ? Number(e.target.dataset.cell) : null;
    if (index === null) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId); // a finger's moves keep coming here
    const paint = !decodeMatrix(current.current)[index];
    stroke.current = { paint, last: index };
    set(index, paint);
  };
  const move = (e: PointerEvent<HTMLDivElement>) => {
    if (stroke.current === null) return;
    const index = cellAt(e.clientX, e.clientY);
    if (index === null || index === stroke.current.last) return;
    stroke.current.last = index;
    set(index, stroke.current.paint);
  };
  const up = () => {
    stroke.current = null;
    edit.release();
  };

  return (
    <>
      <div
        className="draw"
        role="grid"
        aria-label="Mriežka 8×8"
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
      >
        {pixels.map((on, i) => (
          <button
            key={i}
            type="button"
            className="cell"
            data-cell={i}
            aria-label={`riadok ${Math.floor(i / SIZE) + 1}, stĺpec ${(i % SIZE) + 1}`}
            aria-pressed={on}
            // the keyboard: Enter / Space on a cell (a pointer is handled above)
            onClick={(e) => {
              if (e.detail === 0) set(i, !on);
            }}
          />
        ))}
      </div>
      <div className="draw-actions">
        <button
          type="button"
          className="ghost"
          onClick={() => {
            current.current = EMPTY;
            edit.change(EMPTY);
            edit.release();
          }}
        >
          Vymazať
        </button>
        <button type="button" className="ghost" aria-pressed={!showing} onClick={onIcon}>
          Ikona presetu
        </button>
      </div>
      <p className="note">{showing ? "Na stánku svieti tvoja kresba." : "Na stánku svieti ikona presetu. Ťukni do mriežky a kresli."}</p>
    </>
  );
}

