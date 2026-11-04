// At most one send per interval, and never losing the last value (plan step 5):
// a slider being dragged changes 60 times a second, the backend takes 20
// commands a second from a phone (backend.md 9), so the phone sends 10.
//
//   const t = throttle((v) => send(v), 100);
//   t.push(v)    sends now if the interval has passed, otherwise remembers v
//   t.flush()    sends the remembered value now (the finger left the slider)
//
// The first value goes at once; the last one goes at the end of its interval
// even if nothing flushes it.

export interface Throttle<T> {
  push(value: T): void;
  flush(): void;
  cancel(): void;
}

export function throttle<T>(send: (value: T) => void, intervalMs: number): Throttle<T> {
  let last = -Infinity;
  let pending: { value: T } | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const stopTimer = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };
  const fire = () => {
    stopTimer();
    if (pending === null) return;
    const { value } = pending;
    pending = null;
    last = performance.now();
    send(value);
  };

  return {
    push(value) {
      pending = { value };
      const wait = last + intervalMs - performance.now();
      if (wait <= 0) fire();
      else timer ??= setTimeout(fire, wait);
    },
    flush: fire,
    cancel() {
      stopTimer();
      pending = null;
    },
  };
}
