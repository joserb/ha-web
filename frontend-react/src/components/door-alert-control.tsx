import { useEffect, useState } from "react";
import type { ConnectionChain, Sensor } from "@/types/sensors";

export interface NotificationRule {
  sensor_id: string;
  active: boolean;
  enabled_from: number;
  enabled_until: number;
  version: number;
  duration: string;
  last_delivery: { timestamp: number; status: string; detail: string | null } | null;
}
export interface NotificationState { configured: boolean; rules: NotificationRule[] }

// crypto.randomUUID is unavailable on plain HTTP Tailscale origins.
function requestId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function DoorAlertControl({ sensor, state, chain, onChange }: {
  sensor: Sensor;
  state: NotificationState | null;
  chain: ConnectionChain;
  onChange: (state: NotificationState) => void;
}) {
  const [duration, setDuration] = useState("1h");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const rule = state?.rules.find((entry) => entry.sensor_id === sensor.id);
  const active = Boolean(rule?.active && rule.enabled_until * 1000 > now);
  const minutes = rule ? Math.max(0, Math.ceil((rule.enabled_until * 1000 - now) / 60000)) : 0;
  const online = chain.socket === "connected";
  const sourceOnline = chain.mqttConnected && chain.bridgeConnected && chain.piAvailability === "online";
  const controlId = `telegram-${sensor.id}`;

  async function change(enable: boolean) {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/notification-rules/${encodeURIComponent(sensor.id)}`, {
        method: enable ? "PUT" : "DELETE",
        signal: AbortSignal.timeout(10_000),
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(enable
          ? { duration, version: rule?.version ?? 0, request_id: requestId() }
          : { version: rule?.version ?? 0 }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Unable to save alerts");
      onChange(body as NotificationState);
      setNow(Date.now());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to save alerts");
      // The server may have saved a request whose response was lost.
      try {
        const response = await fetch("/api/notification-rules", { signal: AbortSignal.timeout(10_000) });
        if (response.ok) onChange(await response.json() as NotificationState);
      } catch { /* Keep the visible error; reconnect will refresh state. */ }
    } finally { setBusy(false); }
  }

  const failed = rule?.last_delivery && ["failed", "delivery_unknown"].includes(rule.last_delivery.status);
  return <div className="mb-5 rounded-lg border bg-muted/30 p-3">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <label htmlFor={controlId} className="flex cursor-pointer items-center gap-2 text-sm font-medium">
        <input id={controlId} type="checkbox" role="switch" checked={active}
          disabled={busy || !state || !online || (!active && !state.configured)}
          onChange={(event) => void change(event.target.checked)}
          className="relative h-5 w-9 shrink-0 cursor-pointer appearance-none rounded-full bg-muted-foreground/40 transition-colors checked:bg-emerald-600 before:absolute before:left-0.5 before:top-0.5 before:h-4 before:w-4 before:rounded-full before:bg-white before:transition-transform checked:before:translate-x-4 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 motion-reduce:transition-none motion-reduce:before:transition-none" />
        Telegram alerts
      </label>
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          Duration
          <select aria-label={`Alert duration for ${sensor.location_label}`} value={duration} onChange={(event) => setDuration(event.target.value)} disabled={busy}
            className="h-8 rounded-md border bg-background px-2 text-sm text-foreground focus-visible:outline-2">
            {[["1h", "1 hour"], ["4h", "4 hours"], ["8h", "8 hours"], ["1d", "1 day"], ["7d", "7 days"]].map(([value, label]) =>
              <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        {active && <button type="button" disabled={busy || !online || !state?.configured}
          onClick={() => void change(true)} title="Extend to at least this duration from now"
          className="rounded-md border bg-background px-2 py-1 text-sm disabled:opacity-50 focus-visible:outline-2">Extend</button>}
      </div>
    </div>
    <p className="mt-2 text-xs text-muted-foreground" role="status">
      {busy ? "Saving…" : !state ? "Loading alert settings…" : active && rule
        ? `Active until ${new Date(rule.enabled_until * 1000).toLocaleString()} · ${minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`} remaining`
        : "Off · Notify on new door openings only"}
    </p>
    {state && !state.configured && <p className="mt-2 text-xs text-destructive">Telegram is not configured on the server.</p>}
    {!online && <p className="mt-2 text-xs text-destructive">Dashboard disconnected. Alert settings may be outdated.</p>}
    {online && !sourceOnline && <p className="mt-2 text-xs text-destructive">Sensor connection unavailable. Openings may be missed.</p>}
    {sensor.current?.stale && <p className="mt-2 text-xs text-muted-foreground">No recent sensor report. Check the door sensor before relying on alerts.</p>}
    {sensor.current?.payload === "open" && <p className="mt-2 text-xs text-muted-foreground">Door is already open. Alerts start with the next opening.</p>}
    {failed && <p className="mt-2 text-xs text-destructive">Last alert: {rule?.last_delivery?.detail}</p>}
    {rule?.last_delivery?.status === "sent" && <p className="mt-2 text-xs text-muted-foreground">Last alert sent: {new Date(rule.last_delivery.timestamp * 1000).toLocaleString()}</p>}
    {error && <p className="mt-2 text-xs text-destructive" role="alert">{error}</p>}
  </div>;
}
