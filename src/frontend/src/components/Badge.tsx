// The status badge (tech-spec 4.5; plan step 3): is the backend there, is the
// board there. Real problems show up here, never in the fake terminal.
import type { HardwarePart } from "../api/messages";
import type { Status } from "../api/socket";
import { useStand } from "../api/useStand";

export type Tone = "ok" | "warn" | "bad";

export interface BadgeInfo {
  tone: Tone;
  text: string;
  /** More detail on hover: the board's last error. */
  detail?: string;
}

export function badgeFor(status: Status, hardware: HardwarePart | null): BadgeInfo {
  if (status === "connecting") return { tone: "warn", text: "Pripájam sa k serveru…" };
  if (status !== "open") return { tone: "bad", text: "Server nedostupný" };
  if (hardware === null) return { tone: "warn", text: "Čakám na stav…" };
  const detail = hardware.error ?? undefined;
  switch (hardware.state) {
    case "connected":
      return hardware.simulated
        ? { tone: "warn", text: `Simulovaná doska · ${hardware.fps.toFixed(0)} fps` }
        : { tone: "ok", text: `Doska pripojená · ${hardware.fps.toFixed(0)} fps` };
    case "connecting":
      return { tone: "warn", text: "Pripájam dosku…", detail };
    case "incompatible":
      return { tone: "bad", text: "Nekompatibilná doska", detail };
    default:
      return { tone: "bad", text: "Doska odpojená", detail };
  }
}

export function Badge({ status, hardware }: { status: Status; hardware: HardwarePart | null }) {
  const { tone, text, detail } = badgeFor(status, hardware);
  return (
    <span className={`badge ${tone}`} role="status" title={detail} data-tone={tone}>
      <i aria-hidden="true" />
      {text}
    </span>
  );
}

export function LiveBadge() {
  const status = useStand((s) => s.status);
  const hardware = useStand((s) => s.state?.hardware ?? null);
  return <Badge status={status} hardware={hardware} />;
}
