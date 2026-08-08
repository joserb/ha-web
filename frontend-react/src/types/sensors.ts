import type { TimeRange } from "@/lib/ranges";

export interface CurrentReading {
  payload: string;
  updated_at: string;
  source: string;
  age_seconds: number;
  stale: boolean;
}

export interface Sensor {
  id: string;
  topic: string;
  location: string;
  location_label: string;
  measurement: string;
  label: string;
  family: string;
  kind: string;
  card: "meter" | "timeline" | "status";
  unit: string | null;
  minimum: number | null;
  maximum: number | null;
  warning_above: number | null;
  warning_below: number | null;
  stale_after_seconds: number;
  current: CurrentReading | null;
}

export type SocketStatus = "connecting" | "connected" | "disconnected";
export type PiAvailability = "online" | "offline";

/**
 * The three independent legs between this page and the sensors. Each one is
 * reported separately because a healthy WebSocket only proves the browser
 * reached the backend, and a healthy broker only proves the VPS leg. `null`
 * means unknown, never "fine".
 */
export interface ConnectionChain {
  socket: SocketStatus;
  mqttConnected: boolean | null;
  bridgeConnected: boolean | null;
  piAvailability: PiAvailability | null;
}

export interface HistoryPoint {
  time: string;
  field: string;
  value: number;
}

export interface TrendSeries {
  sensor: Sensor;
  points: HistoryPoint[];
}

export interface DashboardPreferences {
  range: TimeRange;
}
