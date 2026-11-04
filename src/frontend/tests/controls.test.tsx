// The phone's controls (plan step 5), built from the presets exactly as the
// backend describes them (src/backend/schema/presets.json, written by
// ./dod schema): a new preset needs no frontend change.
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PRESETS from "../../backend/schema/presets.json";
import type { MusicPart, PresetInfo, SongInfo } from "../src/api/messages";
import { Drawing } from "../src/apps/Manual/Drawing";
import { Params } from "../src/apps/Manual/Params";
import { Presets } from "../src/apps/Manual/Presets";
import { SongList } from "../src/apps/Music/SongList";
import { EMPTY } from "../src/lib/matrix";

const presets = PRESETS as PresetInfo[];
const preset = (id: string): PresetInfo => {
  const p = presets.find((x) => x.id === id);
  if (p === undefined) throw new Error(`no preset ${id} in presets.json`);
  return p;
};
const defaults = (p: PresetInfo) => Object.fromEntries(p.params.map((x) => [x.name, x.default]));

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Params, from the backend's presets", () => {
  it.each(presets.map((p) => [p.id, p] as const))("%s: one control per parameter, of its kind", (_, p) => {
    const { container } = render(<Params params={p.params} values={defaults(p)} onChange={() => {}} />);
    for (const param of p.params) {
      const control = [...container.querySelectorAll(`[data-kind]`)].find((el) => el.textContent?.includes(param.label));
      expect(control, `${p.id}.${param.name}`).toBeDefined();
      expect(control?.getAttribute("data-kind")).toBe(param.kind);
      const c = control as HTMLElement;
      switch (param.kind) {
        case "slider": {
          const input = within(c).getByRole("slider");
          expect(input.getAttribute("min")).toBe(String(param.min));
          expect(input.getAttribute("max")).toBe(String(param.max));
          expect(Number((input as HTMLInputElement).value)).toBeCloseTo(Number(param.default));
          break;
        }
        case "color":
          expect((c.querySelector("input[type=color]") as HTMLInputElement).value).toBe(param.default);
          break;
        case "choice":
          expect(within(c).getAllByRole("button").map((b) => b.textContent)).toEqual(param.options?.map((o) => o.label));
          break;
        case "toggle":
          expect(within(c).getByRole("switch").getAttribute("aria-checked")).toBe(String(param.default));
          break;
      }
    }
    expect(container.querySelectorAll("[data-kind]")).toHaveLength(p.params.length);
  });

  it("the presets have every kind of control between them", () => {
    const kinds = new Set(presets.flatMap((p) => p.params.map((x) => x.kind)));
    expect([...kinds].sort()).toEqual(["choice", "color", "slider", "toggle"]);
  });

  it("shows the state's values, not the defaults", () => {
    render(<Params params={preset("rainbow").params} values={{ speed: 1.5, width: 2, saturation: 0.5, direction: "left" }} onChange={() => {}} />);
    expect((screen.getByLabelText("Rýchlosť") as HTMLInputElement).value).toBe("1.5");
    expect(screen.getByRole("button", { name: "Doľava" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("a dragged slider sends at most 10 values a second, and the last one on release", async () => {
    const onChange = vi.fn();
    render(<Params params={preset("rainbow").params} values={defaults(preset("rainbow"))} onChange={onChange} />);
    const slider = screen.getByLabelText("Rýchlosť");
    for (let i = 1; i <= 60; i++) {
      fireEvent.change(slider, { target: { value: String(0.05 + i * 0.02) } });
      await act(() => vi.advanceTimersByTimeAsync(1000 / 60));
    }
    const sent = onChange.mock.calls.filter(([name]) => name === "speed");
    expect(sent.length).toBeLessThanOrEqual(11);
    fireEvent.pointerUp(slider);
    expect(onChange.mock.calls.at(-1)).toEqual(["speed", 0.05 + 60 * 0.02]);
    expect((slider as HTMLInputElement).value).toBe(String(0.05 + 60 * 0.02)); // shows its own value meanwhile
  });

  it("a toggle and a choice send at once", () => {
    const onChange = vi.fn();
    const { rerender } = render(<Params params={preset("solid").params} values={defaults(preset("solid"))} onChange={onChange} />);
    fireEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenLastCalledWith("fade", true);
    rerender(<Params params={preset("rainbow").params} values={defaults(preset("rainbow"))} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Doľava" }));
    expect(onChange).toHaveBeenLastCalledWith("direction", "left");
  });

  it("a colour is sent in lower case", () => {
    const onChange = vi.fn();
    const { container } = render(<Params params={preset("solid").params} values={defaults(preset("solid"))} onChange={onChange} />);
    fireEvent.change(container.querySelector("#param-color") as HTMLInputElement, { target: { value: "#00FF80" } });
    expect(onChange).toHaveBeenLastCalledWith("color", "#00ff80");
  });

  it("after a while it shows the server's value again", async () => {
    const { rerender } = render(<Params params={preset("rainbow").params} values={{ speed: 0.3 }} onChange={() => {}} />);
    fireEvent.change(screen.getByLabelText("Rýchlosť"), { target: { value: "1" } });
    rerender(<Params params={preset("rainbow").params} values={{ speed: 0.7 }} onChange={() => {}} />); // another screen changed it
    expect((screen.getByLabelText("Rýchlosť") as HTMLInputElement).value).toBe("1");
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect((screen.getByLabelText("Rýchlosť") as HTMLInputElement).value).toBe("0.7");
  });
});

describe("Presets", () => {
  it("a button per preset, the current one pressed; a tap picks", () => {
    const onPick = vi.fn();
    render(<Presets presets={presets} current="rainbow" onPick={onPick} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(presets.map((p) => p.name));
    expect(screen.getByRole("button", { name: "Dúha" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Farba" }));
    expect(onPick).toHaveBeenCalledWith("solid");
  });
});

describe("Drawing", () => {
  const cell = (row: number, col: number) => screen.getByRole("button", { name: `riadok ${row}, stĺpec ${col}` });

  it("a tap switches a pixel and sends the whole drawing", () => {
    const onDraw = vi.fn();
    render(<Drawing drawing={EMPTY} showing={false} onDraw={onDraw} onIcon={() => {}} />);
    fireEvent.pointerDown(cell(1, 1), { pointerId: 1 });
    fireEvent.pointerUp(cell(1, 1), { pointerId: 1 });
    expect(onDraw).toHaveBeenLastCalledWith("8000000000000000");
    expect(cell(1, 1).getAttribute("aria-pressed")).toBe("true");
  });

  it("a tap on a lit pixel erases it", () => {
    const onDraw = vi.fn();
    render(<Drawing drawing="0000000000000001" showing onDraw={onDraw} onIcon={() => {}} />);
    fireEvent.pointerDown(cell(8, 8), { pointerId: 1 });
    fireEvent.pointerUp(cell(8, 8), { pointerId: 1 });
    expect(onDraw).toHaveBeenLastCalledWith(EMPTY);
  });

  it("a drag paints every pixel it crosses, sent at most 10 times a second", async () => {
    const onDraw = vi.fn();
    render(<Drawing drawing={EMPTY} showing onDraw={onDraw} onIcon={() => {}} />);
    const grid = screen.getByRole("grid");
    fireEvent.pointerDown(cell(1, 1), { pointerId: 1 });
    for (let col = 2; col <= 8; col++) {
      // jsdom has no layout: point the finger at the next cell of row 1
      document.elementFromPoint = () => cell(1, col);
      fireEvent.pointerMove(grid, { pointerId: 1, clientX: col, clientY: 1 });
      await act(() => vi.advanceTimersByTimeAsync(16));
    }
    fireEvent.pointerUp(grid, { pointerId: 1 });
    expect(onDraw).toHaveBeenLastCalledWith("ff00000000000000");
    expect(onDraw.mock.calls.length).toBeLessThanOrEqual(3);
  });

  it("Vymazať clears it, Ikona presetu goes back to the icon", () => {
    const onDraw = vi.fn();
    const onIcon = vi.fn();
    render(<Drawing drawing="183c7effff7e3c18" showing onDraw={onDraw} onIcon={onIcon} />);
    fireEvent.click(screen.getByRole("button", { name: "Vymazať" }));
    expect(onDraw).toHaveBeenLastCalledWith(EMPTY);
    fireEvent.click(screen.getByRole("button", { name: "Ikona presetu" }));
    expect(onIcon).toHaveBeenCalledOnce();
  });
});

describe("SongList", () => {
  const songs: SongInfo[] = [
    { id: "dQw4w9WgXcQ", title: "Never Gonna Give You Up", length: 213, ready: true },
    { id: "y6120QOlsfU", title: "Sandstorm", length: null, ready: false },
  ];
  const music = (part: Partial<MusicPart> = {}): MusicPart => ({
    song: null,
    title: null,
    started_at: null,
    length: null,
    playing: false,
    player_connected: true,
    ...part,
  });

  it("downloaded songs can be picked; the others are greyed out", () => {
    const onPick = vi.fn();
    render(<SongList songs={songs} music={music()} onPick={onPick} />);
    const [ready, missing] = screen.getAllByRole("button") as HTMLButtonElement[];
    expect(ready?.disabled).toBe(false);
    expect(ready?.textContent).toContain("3:33");
    expect(missing?.disabled).toBe(true);
    fireEvent.click(ready as HTMLButtonElement);
    expect(onPick).toHaveBeenCalledWith("dQw4w9WgXcQ");
  });

  it("all greyed out while no main screen plays", () => {
    render(<SongList songs={songs} music={music({ player_connected: false })} onPick={() => {}} />);
    expect((screen.getAllByRole("button") as HTMLButtonElement[]).every((b) => b.disabled)).toBe(true);
    expect(screen.getByText(/nehrá/)).toBeTruthy();
  });

  it("shows what plays", () => {
    render(<SongList songs={songs} music={music({ song: "dQw4w9WgXcQ", title: "Never Gonna", playing: true })} onPick={() => {}} />);
    expect(screen.getByText("Hrá: Never Gonna")).toBeTruthy();
    expect(screen.getAllByRole("button")[0]?.getAttribute("aria-pressed")).toBe("true");
  });

  it("no songs yet", () => {
    render(<SongList songs={[]} music={music()} onPick={() => {}} />);
    expect(screen.getByText("Zatiaľ žiadne skladby.")).toBeTruthy();
  });
});
