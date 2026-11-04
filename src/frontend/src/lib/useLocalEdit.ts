// A control's value while someone changes it (plan step 5).
//
// The state from the server is the truth, so two screens never disagree. But
// it arrives a moment after a change, and a slider that jumps back to the old
// value under the finger is unusable. So while a control is being changed
// it shows its own value, and SETTLE_MS after the last change it shows the
// server's again (by then the server has the last value).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { throttle } from "./throttle";

export const SEND_INTERVAL_MS = 100; // 10 a second
const SETTLE_MS = 600;

export interface LocalEdit<T> {
  value: T;
  /** A new value from the control: shown at once, sent throttled. */
  change(value: T): void;
  /** The control was let go: send the last value now. */
  release(): void;
}

export function useLocalEdit<T>(server: T, send: (value: T) => void): LocalEdit<T> {
  const [local, setLocal] = useState<{ value: T } | null>(null);
  const sendRef = useRef(send);
  sendRef.current = send;
  const settle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const t = useMemo(() => throttle<T>((v) => sendRef.current(v), SEND_INTERVAL_MS), []);

  useEffect(
    () => () => {
      t.flush(); // a control that goes away (the preset changed) still sends its last value
      if (settle.current !== null) clearTimeout(settle.current);
    },
    [t],
  );

  const change = useCallback(
    (value: T) => {
      setLocal({ value });
      t.push(value);
      if (settle.current !== null) clearTimeout(settle.current);
      settle.current = setTimeout(() => setLocal(null), SETTLE_MS);
    },
    [t],
  );

  return { value: local === null ? server : local.value, change, release: t.flush };
}
