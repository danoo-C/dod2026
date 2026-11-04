// A placeholder per route (plan step 1): which screen this is, and whether
// the backend answers. Replaced by the real screens in steps 4-6.
import { useEffect, useState } from "react";

import type { Role } from "../api/roles";

const NAMES: Record<Role, string> = {
  phone: "Mobil návštevníka",
  main: "Obrazovka notebooku",
  logging: "Terminál",
};

type Health = "checking" | "ok" | "down";

export function Hello({ role }: { role: Role }) {
  const [health, setHealth] = useState<Health>("checking");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/health")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((body: { status?: string }) => !cancelled && setHealth(body.status === "ok" ? "ok" : "down"))
      .catch(() => !cancelled && setHealth("down"));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", color: "#eef0fb" }}>
      <h1>DOD 2026</h1>
      <p>
        {NAMES[role]} (<code>{role}</code>)
      </p>
      <p data-testid="health">
        Backend:{" "}
        {health === "checking" ? "overujem…" : health === "ok" ? "beží" : "neodpovedá"}
      </p>
    </main>
  );
}
