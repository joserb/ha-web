import { useEffect, useRef, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useCameraStream } from "@/hooks/use-camera-stream";

const STREAM_PATH = "/camera/home/ws";
// Scrolling past the card is not a request to stop watching, so a short grace
// period avoids tearing the stream down on a flick of the scroll wheel.
const OUT_OF_VIEW_GRACE_MS = 3_000;

/**
 * Live view of the home camera. The card renders its own section so that the
 * deployment switch removes the heading too, and it never depends on
 * `useDashboardData`: a failing sensor API must not take the camera with it,
 * and an unreachable camera must not touch sensors or alerts.
 */
export function CameraCard() {
  const [enabled, setEnabled] = useState(false);
  const { videoRef, status, error, interrupted, start, stop, suspend } = useCameraStream(STREAM_PATH);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [muted, setMuted] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/camera/config.json", { signal: controller.signal })
      .then((response) => response.ok ? response.json() as Promise<{ enabled?: boolean }> : { enabled: false })
      .then((config) => setEnabled(config.enabled === true))
      .catch(() => { /* No gateway configured: the card simply stays hidden. */ });
    return () => controller.abort();
  }, []);

  const watching = status === "connecting" || status === "live" || status === "reconnecting";

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !watching) return;
    let timer: number | undefined;
    const observer = new IntersectionObserver(([entry]) => {
      window.clearTimeout(timer);
      if (!entry.isIntersecting) timer = window.setTimeout(suspend, OUT_OF_VIEW_GRACE_MS);
    }, { threshold: 0.1 });
    observer.observe(frame);
    return () => { window.clearTimeout(timer); observer.disconnect(); };
  }, [watching, suspend]);

  if (!enabled) return null;

  const label = {
    unsupported: "Video playback is not supported by this browser",
    idle: interrupted ? "Paused while not visible" : "Ready to connect",
    connecting: "Connecting…",
    live: "Live",
    reconnecting: error ? `Reconnecting… · ${error}` : "Reconnecting…",
    error: error ?? "Camera unavailable",
  }[status];

  return <section className="mt-8 space-y-4" aria-labelledby="camera-heading">
    <h2 id="camera-heading" className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Camera</h2>
    <Card className="max-w-3xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Home camera
          {/* Only moving video earns the badge: the hook drops out of `live`
              as soon as playback stops advancing. */}
          {status === "live" && <span className="inline-flex items-center gap-1.5 rounded-full bg-red-600/10 px-2 py-0.5 text-xs font-medium text-red-600 dark:text-red-400">
            <span className="h-1.5 w-1.5 rounded-full bg-red-600 dark:bg-red-400" aria-hidden="true" />LIVE
          </span>}
        </CardTitle>
        <CardDescription role="status">{label}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div ref={frameRef} className="relative aspect-video overflow-hidden rounded-lg bg-black">
          {/* No native controls: pausing would leave a frozen frame that the
              card would still have to label something. Stop, Mute and
              Fullscreen are buttons below, reachable by keyboard. */}
          <video
            ref={videoRef}
            muted={muted}
            playsInline
            className="h-full w-full object-contain"
            aria-label="Home camera live video"
          />
          {status !== "live" && <div className="absolute inset-0 flex items-center justify-center p-4 text-center text-sm text-white/70">
            {status === "connecting" || status === "reconnecting" ? "Connecting…" : label}
          </div>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {status === "idle" && <button type="button" onClick={start}
            className="rounded-md border bg-background px-3 py-1.5 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2">
            {interrupted ? "Resume live" : "View live"}
          </button>}
          {status === "error" && <button type="button" onClick={start}
            className="rounded-md border bg-background px-3 py-1.5 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2">Retry</button>}
          {watching && <button type="button" onClick={stop}
            className="rounded-md border bg-background px-3 py-1.5 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2">Stop</button>}
          {/* Audio stays out of the way until asked for: the stream starts
              muted so playback is allowed without a gesture, and a camera that
              sends no audio track still shows video. */}
          <button type="button" onClick={() => setMuted((value) => !value)} disabled={status !== "live"}
            className="rounded-md border bg-background px-3 py-1.5 text-sm disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2">
            {muted ? "Unmute" : "Mute"}
          </button>
          <button type="button" disabled={status !== "live"}
            onClick={() => void frameRef.current?.requestFullscreen?.().catch(() => { /* Denied or unsupported: stay inline. */ })}
            className="rounded-md border bg-background px-3 py-1.5 text-sm disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2">Fullscreen</button>
        </div>
        {status === "error" && <p className="text-xs text-destructive" role="alert">{error}</p>}
        <p className="text-xs text-muted-foreground">Video is requested only while you watch it and is not recorded.</p>
      </CardContent>
    </Card>
  </section>;
}
