import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  archiveEvent, archiveTrack, deletePerson, deleteTrack, fetchPresence, labelTrack, renamePerson, trackImageUrl,
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
  const [showArchived, setShowArchived] = useState(false);

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
    fetchPresence(showArchived, controller.signal)
      .then((next) => { setState(next); setError(null); })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Presence unavailable");
      });
    return () => controller.abort();
  }, [enabled, version, showArchived]);

  if (!enabled) return null;

  async function run(action: () => Promise<PresenceState>) {
    setBusy(true);
    try {
      await action();
      // Refetched rather than taken from the reply, which never includes
      // archived rows.
      setState(await fetchPresence(showArchived));
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
        {state && <Events events={state.events.slice(0, EVENT_LIMIT)} people={state.people} busy={busy} run={run}
          showArchived={showArchived} onShowArchived={setShowArchived} />}
        {error && state && <p className="text-xs text-destructive" role="alert">{error}</p>}
        {state && <p className="text-xs text-muted-foreground">
          Images and face matching stay on this server. Events and their images are deleted after
          {" "}{state.retention_days} days; labelled faces stay until you delete the person.
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
      Nobody is known yet. Use “Who is it?” on the door events below after someone comes in or goes out.
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

function Events({ events, people, busy, run, showArchived, onShowArchived }: {
  events: PresenceEvent[]; people: PresencePerson[]; busy: boolean; run: Run;
  showArchived: boolean; onShowArchived: (value: boolean) => void;
}) {
  return <section aria-labelledby="presence-events">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 id="presence-events" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Door events</h3>
      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <input type="checkbox" checked={showArchived} onChange={(event) => onShowArchived(event.target.checked)} />
        Show archived
      </label>
    </div>
    {!events.length ? <p className="mt-2 text-sm text-muted-foreground">{showArchived ? "No door events yet" : "Nothing left to review"}</p>
      : <ol className="mt-2 divide-y">
        {events.map((event) => <li key={event.id} className="py-2">
          <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
            <time dateTime={new Date(event.opened_at * 1000).toISOString()} className="tabular-nums">{formatTime(event.opened_at)}</time>
            {event.status === "no_video" && <span className="text-muted-foreground">Door opened · no camera video</span>}
            {event.status !== "no_video" && event.people.length === 0 && <span className="text-muted-foreground">Door opened · nobody seen</span>}
            {event.archived && <span className="text-xs text-muted-foreground">(archived)</span>}
            {event.people.length === 0 && !event.archived &&
              <button type="button" className={BUTTON} disabled={busy} onClick={() => void run(() => archiveEvent(event.id))}>Archive</button>}
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
  const [broken, setBroken] = useState(false);
  const label = track.name ?? "Unknown person";

  function save() {
    const target = choice ? { person_id: Number(choice) } : { name: name.trim() };
    if ("name" in target && !target.name) return;
    void run(() => labelTrack(track.id, target)).then(() => setLabelling(false));
  }

  return <li className={`flex flex-wrap items-center gap-3 text-sm ${track.archived ? "opacity-60" : ""}`}>
    {/* The whole person in their clearest frame: people going out show their
        back, so a face crop alone left most of the log blank. */}
    {track.has_image && !broken
      ? <a href={trackImageUrl(track.id)} target="_blank" rel="noreferrer" title="Open full size"
          className="shrink-0 rounded-md focus-visible:outline-2 focus-visible:outline-offset-2">
          <img src={trackImageUrl(track.id)} alt={label} loading="lazy" onError={() => setBroken(true)}
            className="h-20 w-auto max-w-32 rounded-md bg-muted object-contain" />
        </a>
      : <span className="flex h-20 w-14 shrink-0 items-center justify-center rounded-md bg-muted text-center text-[10px] leading-tight text-muted-foreground">No image</span>}
    <span>
      <span className="font-medium">{label}</span>
      {" "}{DIRECTION_TEXT[track.direction]}
      {track.confidence !== "high" && track.identity !== "manual" && <span className="text-muted-foreground"> ({track.confidence} confidence)</span>}
      {track.archived && <span className="text-xs text-muted-foreground"> · archived</span>}
    </span>
    {!labelling && <>
      <button type="button" className={BUTTON} disabled={busy} onClick={() => setLabelling(true)}>
        {track.identity === "manual" ? "Relabel" : track.name ? "Not them?" : "Who is it?"}
      </button>
      {!track.archived && <button type="button" className={BUTTON} disabled={busy}
        title={track.name ? `Confirm it is ${track.name} and hide it from the log` : "Keep it as an unknown person and hide it from the log"}
        onClick={() => void run(() => archiveTrack(track.id))}>{track.name ? "Correct · archive" : "Archive"}</button>}
      <button type="button" className={`${BUTTON} text-destructive`} disabled={busy}
        title="Erase this detection and its image; it will not count for anyone"
        onClick={() => {
          if (window.confirm("Delete this detection and its image? It will no longer count for anyone.")) void run(() => deleteTrack(track.id));
        }}>Delete</button>
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
