// How components reach the connection (plan step 2):
//
//   <StandProvider role="phone"> … </StandProvider>   one per screen, connects while mounted
//   const you = useStand((s) => s.you);                 re-renders only when that part changes
//   const stand = useStandActions();                    stand.send({...}), stand.takeOver()
//
// Pick the smallest part you need: previews arrive 10 times a second, and a
// component that reads the whole snapshot re-renders with every one of them.
import { createContext, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";

import type { ServerClock } from "./clock";
import type { Role } from "./roles";
import { Stand, type Snapshot } from "./store";

const StandContext = createContext<Stand | null>(null);

export function StandProvider({ role, stand, children }: { role: Role; stand?: Stand; children: ReactNode }) {
  // one Stand per provider; tests pass their own
  const [current] = useState(() => stand ?? new Stand(role));
  useEffect(() => {
    current.start();
    return () => current.stop(); // React's StrictMode mounts twice in development: stop, start again
  }, [current]);
  return <StandContext.Provider value={current}>{children}</StandContext.Provider>;
}

function useStandContext(): Stand {
  const stand = useContext(StandContext);
  if (stand === null) throw new Error("useStand() outside <StandProvider>");
  return stand;
}

export function useStand<T>(select: (snapshot: Snapshot) => T): T {
  const { store } = useStandContext();
  return useSyncExternalStore(store.subscribe, () => select(store.get()));
}

export function useStandActions(): Pick<Stand, "send" | "takeOver" | "role"> {
  return useStandContext();
}

export function useServerClock(): ServerClock {
  return useStandContext().store.clock;
}
