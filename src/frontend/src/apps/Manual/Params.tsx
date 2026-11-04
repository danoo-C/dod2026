// The current preset's parameters (plan step 5; backend.md 7.2): one control
// per `ParamInfo`, by its kind, with the backend's Slovak label. The values
// shown are the state's, so the phone and the main screen never disagree;
// while a control is being changed it shows its own (useLocalEdit).
import type { ParamInfo } from "../../api/messages";
import { decimal } from "../../lib/slovak";
import { useLocalEdit } from "../../lib/useLocalEdit";

export type ParamValue = boolean | number | string; // as in the state's manual.params
export type SetParam = (name: string, value: ParamValue) => void;

export function Params({
  params,
  values,
  onChange,
}: {
  params: readonly ParamInfo[];
  values: Readonly<Record<string, ParamValue>>;
  onChange: SetParam;
}) {
  if (params.length === 0) return <p className="note">Tento preset nemá nastavenia.</p>;
  return (
    <div className="params">
      {params.map((p) => (
        <Control key={p.name} param={p} value={values[p.name] ?? p.default} onChange={(v) => onChange(p.name, v)} />
      ))}
    </div>
  );
}

function Control({ param, value, onChange }: { param: ParamInfo; value: ParamValue; onChange(v: ParamValue): void }) {
  switch (param.kind) {
    case "slider":
      return <Slider param={param} value={Number(value)} onChange={onChange} />;
    case "color":
      return <Color param={param} value={String(value)} onChange={onChange} />;
    case "choice":
      return <Choice param={param} value={String(value)} onChange={onChange} />;
    case "toggle":
      return <Toggle param={param} value={value === true} onChange={onChange} />;
  }
}

const id = (p: ParamInfo) => `param-${p.name}`;

function Slider({ param, value, onChange }: { param: ParamInfo; value: number; onChange(v: number): void }) {
  const edit = useLocalEdit(value, onChange);
  return (
    <div className="slider" data-kind="slider">
      <label htmlFor={id(param)}>{param.label}</label>
      <input
        id={id(param)}
        type="range"
        min={param.min ?? 0}
        max={param.max ?? 1}
        step={param.step ?? "any"}
        value={edit.value}
        onChange={(e) => edit.change(Number(e.currentTarget.value))}
        onPointerUp={edit.release}
        onKeyUp={edit.release}
        onBlur={edit.release}
      />
      <output htmlFor={id(param)}>{decimal(edit.value, param.step)}</output>
    </div>
  );
}

function Color({ param, value, onChange }: { param: ParamInfo; value: string; onChange(v: string): void }) {
  const edit = useLocalEdit(value, onChange);
  return (
    <div className="color-row" data-kind="color">
      <label htmlFor={id(param)}>{param.label}</label>
      <input
        id={id(param)}
        type="color"
        value={edit.value}
        onChange={(e) => edit.change(e.currentTarget.value.toLowerCase())}
        onBlur={edit.release}
      />
    </div>
  );
}

function Choice({ param, value, onChange }: { param: ParamInfo; value: string; onChange(v: string): void }) {
  const edit = useLocalEdit(value, onChange);
  return (
    <div className="choice" data-kind="choice" role="group" aria-label={param.label}>
      <span className="choice-label">{param.label}</span>
      <div className="seg">
        {(param.options ?? []).map((o) => (
          <button key={o.value} type="button" aria-pressed={edit.value === o.value} onClick={() => edit.change(o.value)}>
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Toggle({ param, value, onChange }: { param: ParamInfo; value: boolean; onChange(v: boolean): void }) {
  const edit = useLocalEdit(value, onChange);
  return (
    <div className="toggle-row" data-kind="toggle">
      <span id={id(param)}>{param.label}</span>
      <button
        type="button"
        role="switch"
        className="switch"
        aria-checked={edit.value}
        aria-labelledby={id(param)}
        onClick={() => edit.change(!edit.value)}
      >
        <i aria-hidden="true" />
      </button>
    </div>
  );
}
