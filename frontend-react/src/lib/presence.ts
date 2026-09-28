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
  has_image: boolean;
  archived: boolean;
  name: string | null;
}

export interface PresenceEvent {
  id: number;
  opened_at: number;
  closed_at: number | null;
  analysed_at: number;
  status: "ok" | "nobody_seen" | "no_video";
  frames: number;
  archived: boolean;
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

export async function fetchPresence(includeArchived: boolean, signal?: AbortSignal): Promise<PresenceState> {
  const response = await fetch(`/api/presence/state${includeArchived ? "?include_archived=true" : ""}`, { signal });
  if (!response.ok) throw new Error(`Presence service unavailable (${response.status})`);
  return response.json() as Promise<PresenceState>;
}

export const labelTrack = (trackId: number, target: { person_id: number } | { name: string }) =>
  send("POST", `/tracks/${trackId}/label`, target);
// Archive: the identification is right; keep it counting for who is home but
// take it out of the log. Delete: wrong or unwanted; the detection, its image
// and its face are erased and it no longer counts for anyone.
export const archiveTrack = (trackId: number) => send("POST", `/tracks/${trackId}/archive`, {});
export const deleteTrack = (trackId: number) => send("DELETE", `/tracks/${trackId}`, {});
export const archiveEvent = (eventId: number) => send("POST", `/events/${eventId}/archive`, {});
export const renamePerson = (personId: number, name: string) => send("PATCH", `/people/${personId}`, { name });
export const deletePerson = (personId: number) => send("DELETE", `/people/${personId}`, {});

export const trackImageUrl = (trackId: number) => `/api/presence/tracks/${trackId}/image`;
