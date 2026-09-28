import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  deletePerson, faceImageUrl, fetchPresence, ignoreFace, labelFace, renamePerson,
  type PresenceEvent, type PresencePerson, type PresenceState, type PresenceTrack,
} from "@/lib/presence";

const EVENT_LIMIT = 10;
const BUTTON = "rounded-md border bg-background px-2 py-1 text-xs font-medium disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2";

const DIRECTION_TEXT: Record<PresenceTrack["direction"], string> = {
  entered: "came in",
  left: "went out",
  stayed: "stayed in",
  unclear: "direction unclear",
};

function formatTime(seconds: number): string {
  const date = new Date(seconds * 1000);
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/**
 * Who came in or went out through the entrance door, from the camera. Like the
 * camera card it lives outside the sensor gate and keeps its failures inside:
 * the presence service is optional and may be down on its own.
 */
export function PresenceCard({ version }: { version: number }) {
  const [enabled, setEnabled] = useState(false);
  const [state, setState] = useState<PresenceState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/camera/config.json", { signal: controller.signal })
      .then((response) => response.ok ? response.json() as Promise<{ presence?: boolean }> : { presence: false })
      .then((config) => setEnabled(config.presence === true))
      .catch(() => { /* No presence configured: the card stays hidden. */ });
    return () => controller.abort();
  }, []);

  // `version` changes with every presence message on the dashboard socket.
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    fetchPresence(controller.signal)
      .then((next) => { setState(next); setError(null); })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Presence unavailable");
      });
    return () => controller.abort();
  }, [enabled, version]);

  if (!enabled) return null;

  async function run(action: () => Promise<PresenceState>) {
    setBusy(true);
    try {
      setState(await action());
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Change failed");
    } finally {
      setBusy(false);
    }
  }

  const stream = state?.stream;
  const watching = stream?.connected
    ? stream.mode === "preroll" ? "Watching the door" : "Camera connects when the door opens"
    : state?.camera_configured ? `Camera unavailable${stream?.error ? ` · ${stream.error}` : ""}` : "Camera not configured";

  return <section className="mt-8 space-y-4" aria-labelledby="presence-heading">
    <h2 id="presence-heading" className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Presence</h2>
    <Card className="max-w-3xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Who's home
          {state?.analysing && <span className="rounded-full bg-sky-600/10 px-2 py-0.5 text-xs font-medium text-sky-700 dark:text-sky-300">Analysing…</span>}
        </CardTitle>
        <CardDescription role="status">{state ? watching : error ?? "Loading…"}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {state && <People people={state.people} busy={busy} run={run} />}
        {state && <Events events={state.events.slice(0, EVENT_LIMIT)} people={state.people} busy={busy} run={run} />}
        {error && state && <p className="text-xs text-destructive" role="alert">{error}</p>}
        {state && <p className="text-xs text-muted-foreground">
          Faces are matched on this server only. Unlabelled face crops are deleted after {state.retention_days} days;
          labelled ones stay until you delete the person.
        </p>}
      </CardContent>
    </Card>
  </section>;
}

type Run = (action: () => Promise<PresenceState>) => Promise<void>;

function People({ people, busy, run }: { people: PresencePerson[]; busy: boolean; run: Run }) {
  const [editing, setEditing] = useState(false);
  if (!people.length) {
    return <p className="text-sm text-muted-foreground">
      Nobody is known yet. Label the faces below after someone comes in or goes out.
    </p>;
  }
  return <div>
    <ul className="flex flex-wrap gap-2">
      {people.map((person) => <li key={person.id}
        className="flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm">
        <span className={`h-2 w-2 rounded-full ${person.state === "home" ? "bg-emerald-600" : person.state === "away" ? "bg-muted-foreground/50" : "border border-muted-foreground/50"}`} aria-hidden="true" />
        <span className="font-medium">{person.name}</span>
        <span className="text-muted-foreground">
          {person.state === "home" ? "Home" : person.state === "away" ? "Away" : "Unknown"}
          {person.since !== null && ` · since ${formatTime(person.since)}`}
          {person.confidence === "low" && " (unsure)"}
        </span>
        {editing && <>
          <button type="button" className={BUTTON} disabled={busy} onClick={() => {
            const name = window.prompt("New name", person.name)?.trim();
            if (name && name !== person.name) void run(() => renamePerson(person.id, name));
          }}>Rename</button>
          <button type="button" className={BUTTON} disabled={busy} onClick={() => {
            if (window.confirm(`Delete ${person.name} and their ${person.samples} face samples?`)) void run(() => deletePerson(person.id));
          }}>Delete</button>
        </>}
      </li>)}
    </ul>
    <button type="button" className={`${BUTTON} mt-2`} onClick={() => setEditing((value) => !value)}>
      {editing ? "Done" : "Manage people"}
    </button>
  </div>;
}

function Events({ events, people, busy, run }: { events: PresenceEvent[]; people: PresencePerson[]; busy: boolean; run: Run }) {
  return <section aria-labelledby="presence-events">
    <h3 id="presence-events" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Door events</h3>
    {!events.length ? <p className="mt-2 text-sm text-muted-foreground">No door events yet</p>
      : <ol className="mt-2 divide-y">
        {events.map((event) => <li key={event.id} className="py-2">
          <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
            <time dateTime={new Date(event.opened_at * 1000).toISOString()} className="tabular-nums">{formatTime(event.opened_at)}</time>
            {event.status === "no_video" && <span className="text-muted-foreground">Door opened · no camera video</span>}
            {event.status === "nobody_seen" && <span className="text-muted-foreground">Door opened · nobody seen</span>}
            {event.status === "ok" && event.people.length === 0 && <span className="text-muted-foreground">Door opened · detections dismissed</span>}
          </div>
          {event.people.length > 0 && <ul className="mt-1.5 space-y-1.5">
            {event.people.map((track) => <Track key={track.id} track={track} people={people} busy={busy} run={run} />)}
          </ul>}
        </li>)}
      </ol>}
  </section>;
}

function Track({ track, people, busy, run }: { track: PresenceTrack; people: PresencePerson[]; busy: boolean; run: Run }) {
  const [labelling, setLabelling] = useState(false);
  const [choice, setChoice] = useState("");
  const [name, setName] = useState("");
  const faceId = track.face_id;

  function save() {
    if (faceId === null) return;
    const target = choice ? { person_id: Number(choice) } : { name: name.trim() };
    if ("name" in target && !target.name) return;
    void run(() => labelFace(faceId, target)).then(() => setLabelling(false));
  }

  return <li className="flex flex-wrap items-center gap-2 text-sm">
    {faceId !== null
      ? <img src={faceImageUrl(faceId)} alt={track.name ?? "Unknown person"} width={40} height={40}
          className="h-10 w-10 rounded-md bg-muted object-cover" />
      : <span className="flex h-10 w-10 items-center justify-center rounded-md bg-muted text-xs text-muted-foreground" aria-hidden="true">?</span>}
    <span>
      <span className="font-medium">{track.name ?? "Unknown person"}</span>
      {" "}{DIRECTION_TEXT[track.direction]}
      {track.confidence !== "high" && <span className="text-muted-foreground"> ({track.confidence} confidence)</span>}
    </span>
    {faceId !== null && !labelling && <>
      <button type="button" className={BUTTON} disabled={busy} onClick={() => setLabelling(true)}>
        {track.identity === "manual" ? "Relabel" : track.name ? "Not them?" : "Label"}
      </button>
      <button type="button" className={BUTTON} disabled={busy} onClick={() => void run(() => ignoreFace(faceId))}>Dismiss</button>
    </>}
    {labelling && <form className="flex flex-wrap items-center gap-2" onSubmit={(event) => { event.preventDefault(); save(); }}>
      {people.length > 0 && <select value={choice} onChange={(event) => setChoice(event.target.value)} aria-label="Person"
        className="h-7 rounded-md border bg-background px-2 text-xs">
        <option value="">New person…</option>
        {people.map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}
      </select>}
      {!choice && <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Name" maxLength={40}
        aria-label="New person's name" className="h-7 w-32 rounded-md border bg-background px-2 text-xs" autoFocus />}
      <button type="submit" className={BUTTON} disabled={busy || (!choice && !name.trim())}>Save</button>
      <button type="button" className={BUTTON} onClick={() => setLabelling(false)}>Cancel</button>
    </form>}
  </li>;
}
