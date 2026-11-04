// The presets as big buttons (plan step 5), from `welcome.presets`: a new
// preset on the backend shows up here by itself.
import type { PresetInfo } from "../../api/messages";

/** A swatch per preset id, as in the mockup; a new preset gets the plain one. */
const SWATCH: Record<string, string> = {
  rainbow: "sw-rainbow",
  fire: "sw-fire",
  police: "sw-police",
  breathe: "sw-breathe",
  comet: "sw-comet",
  strobe: "sw-strobe",
  solid: "sw-solid",
};

export function Presets({
  presets,
  current,
  onPick,
}: {
  presets: readonly PresetInfo[];
  current: string | null;
  onPick(id: string): void;
}) {
  return (
    <div className="presets">
      {presets.map((p) => (
        <button
          key={p.id}
          type="button"
          className="preset"
          aria-pressed={p.id === current}
          onClick={() => onPick(p.id)}
        >
          <i className={SWATCH[p.id] ?? "sw-plain"} aria-hidden="true" />
          {p.name}
        </button>
      ))}
    </div>
  );
}
