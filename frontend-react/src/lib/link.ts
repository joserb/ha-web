import type { ConnectionChain } from "@/types/sensors";

/**
 * Verdict on the last leg of the chain: VPS ↔ pihomeblk-1, derived from the two
 * raw facts the backend pushes.
 *
 *   'up'        bridge connected and the zro-pi service alive.
 *   'degraded'  bridge connected but the service on the Pi is dead: MQTT still
 *               reaches the Pi's broker, yet nothing there is publishing.
 *   'down'      bridge disconnected — nothing reaches the house sensors.
 *   'unknown'   no bridge notification seen (our socket is down, or a broker
 *               without the bridge configured).
 */
export type PiStatus = "up" | "degraded" | "down" | "unknown";

export function piStatus(chain: ConnectionChain): PiStatus {
  if (chain.bridgeConnected === null) return "unknown";
  // The bridge WINS over availability: with the link down, the retained
  // `online` we still hold was published before it broke. It says nothing about
  // the Pi now, and showing it would claim the house is reporting at the exact
  // moment it is unreachable.
  if (!chain.bridgeConnected) return "down";
  if (chain.piAvailability === "offline") return "degraded";
  // Bridge up and availability 'online' — or never reported at all. A connected
  // bridge already proves the Pi's broker accepts connections, so a missing
  // last will must not read as an outage.
  return "up";
}

type Tone = "ok" | "pending" | "warn" | "bad" | "unknown";

const DOT: Record<Tone, string> = {
  ok: "bg-emerald-500",
  pending: "bg-amber-500 animate-pulse",
  warn: "bg-amber-500",
  bad: "bg-destructive",
  unknown: "bg-muted-foreground",
};

const CHIP: Record<Tone, string> = {
  ok: "bg-muted text-foreground",
  pending: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  warn: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  bad: "bg-destructive/15 text-destructive",
  unknown: "bg-muted text-muted-foreground",
};

export interface LinkView {
  label: string;
  hint: string;
  tone: Tone;
  dotClass: string;
}

function view(label: string, hint: string, tone: Tone): LinkView {
  return { label, hint, tone, dotClass: DOT[tone] };
}

/** Browser ↔ this backend: the dashboard's own WebSocket. */
export function browserLink(chain: ConnectionChain): LinkView {
  const hint = "Browser ↔ dashboard backend (WebSocket)";
  if (chain.socket === "connected") return view("Dashboard connected", hint, "ok");
  if (chain.socket === "connecting") return view("Connecting to dashboard…", hint, "pending");
  return view("Dashboard offline", hint, "bad");
}

/** Backend ↔ Mosquitto on the VPS. Unknown while our own socket is down. */
export function brokerLink(chain: ConnectionChain): LinkView {
  const hint = "Dashboard backend ↔ MQTT broker (VPS)";
  if (chain.mqttConnected === null) return view("Broker unknown", hint, "unknown");
  return chain.mqttConnected
    ? view("Broker connected", hint, "ok")
    : view("Broker disconnected", hint, "bad");
}

/** VPS ↔ pihomeblk-1: Mosquitto bridge + the zro-pi service on the Pi. */
export function houseLink(chain: ConnectionChain): LinkView {
  const hint = "MQTT bridge ↔ pihomeblk-1 (sensor source)";
  switch (piStatus(chain)) {
    case "up":
      return view("pihomeblk-1 reporting", hint, "ok");
    case "degraded":
      // Its own colour on purpose: the bridge is up, so the repair is on the
      // Pi's service, not on the link.
      return view("pihomeblk-1 service down", hint, "warn");
    case "down":
      return view("Bridge to pihomeblk-1 down", hint, "bad");
    default:
      return view("pihomeblk-1 unknown", hint, "unknown");
  }
}

/**
 * The chain runs browser → backend → broker → Pi. Once a leg is broken every
 * leg behind it is unknowable, so the FIRST broken one names and colours the
 * chip: it is also the one to repair. Green "Live" only when all three hold.
 */
export function summarize(chain: ConnectionChain): LinkView & { chipClass: string } {
  const legs = [browserLink(chain), brokerLink(chain), houseLink(chain)];
  const broken = legs.find((leg) => leg.tone !== "ok");
  const summary = broken ?? view("Live", "Browser, broker and pihomeblk-1 all connected", "ok");
  return { ...summary, chipClass: CHIP[summary.tone] };
}

/** Honest subtitle: only claim live conditions when the Pi is actually reporting. */
export function chainSubtitle(chain: ConnectionChain): string {
  if (chain.socket !== "connected" || chain.mqttConnected === false) {
    return "Last known values — dashboard is not receiving updates";
  }
  switch (piStatus(chain)) {
    case "up":
      return "Live conditions from pihomeblk-1";
    case "degraded":
      return "Last known values — the zro-pi service on pihomeblk-1 is down";
    case "down":
      return "Last known values — no link to pihomeblk-1";
    default:
      return "Conditions from pihomeblk-1 — link state unknown";
  }
}
