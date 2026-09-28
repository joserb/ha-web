export type Direction = "entered" | "left" | "stayed" | "unclear";
export type Confidence = "high" | "medium" | "low";

export interface PresencePerson {
  id: number;
  name: string;
  samples: number;
  state: "home" | "away" | null;
  since: number | null;
  confidence: Confidence | null;
}

export interface PresenceTrack {
  id: number;
  first_t: number;
  last_t: number;
  direction: Direction;
  confidence: Confidence;
  person_id: number | null;
  identity: "auto" | "manual";
  score: number;
  face_id: number | null;
  name: string | null;
}

export interface PresenceEvent {
  id: number;
  opened_at: number;
  closed_at: number | null;
  analysed_at: number;
  status: "ok" | "nobody_seen" | "no_video";
  frames: number;
  people: PresenceTrack[];
}

export interface PresenceState {
  enabled: boolean;
  camera_configured: boolean;
  mqtt_connected: boolean;
  analysing: boolean;
  last_error: string | null;
  stream: { connected: boolean; mode: "preroll" | "on_demand"; buffered_seconds: number; error: string | null } | null;
  retention_days: number;
  people: PresencePerson[];
  events: PresenceEvent[];
}

async function send(method: string, path: string, body: object): Promise<PresenceState> {
  const response = await fetch(`/api/presence${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new Error(typeof detail?.detail === "string" ? detail.detail : `Request failed (${response.status})`);
  }
  return response.json() as Promise<PresenceState>;
}

export async function fetchPresence(signal?: AbortSignal): Promise<PresenceState> {
  const response = await fetch("/api/presence/state", { signal });
  if (!response.ok) throw new Error(`Presence service unavailable (${response.status})`);
  return response.json() as Promise<PresenceState>;
}

export const labelFace = (faceId: number, target: { person_id: number } | { name: string }) =>
  send("POST", `/faces/${faceId}/label`, target);
export const ignoreFace = (faceId: number) => send("POST", `/faces/${faceId}/ignore`, {});
export const renamePerson = (personId: number, name: string) => send("PATCH", `/people/${personId}`, { name });
export const deletePerson = (personId: number) => send("DELETE", `/people/${personId}`, {});

export const faceImageUrl = (faceId: number) => `/api/presence/faces/${faceId}/image`;
