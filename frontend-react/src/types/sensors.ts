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
