import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { TimeRange } from "@/lib/ranges";
import type { Sensor } from "@/types/sensors";

interface Timeline { range_start: string; range_end: string; intervals: Array<{ start: string; end: string; active: boolean }> }
interface WindowRange { start: number; end: number }

function formatTick(value: number, span: number) {
  const date = new Date(value);
  if (span > 36 * 60 * 60 * 1000) {
    return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function EventTimelineCard({ sensor, range }: { sensor: Sensor; range: TimeRange }) {
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [zoom, setZoom] = useState<WindowRange | null>(null);
  const [selection, setSelection] = useState<{ anchor: number; current: number } | null>(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const latestReading = sensor.current?.updated_at;
  useEffect(() => {
    const query = new URLSearchParams({ sensor_id: sensor.id, range });
    fetch(`/api/intervals?${query}`).then((response) => response.json()).then(setTimeline).catch(() => setTimeline(null));
  }, [sensor.id, range, latestReading]);
  useEffect(() => setZoom(null), [range]);
  const fullStart = timeline ? new Date(timeline.range_start).getTime() : 0;
  const fullEnd = timeline ? new Date(timeline.range_end).getTime() : 1;
  const start = zoom?.start ?? fullStart;
  const end = zoom?.end ?? fullEnd;
  const span = Math.max(1, end - start);
  const visibleIntervals = useMemo(() => timeline?.intervals.flatMap((item) => {
    const itemStart = Math.max(start, new Date(item.start).getTime());
    const itemEnd = Math.min(end, new Date(item.end).getTime());
    return itemEnd > itemStart ? [{ ...item, visibleStart: itemStart, visibleEnd: itemEnd }] : [];
  }) ?? [], [timeline, start, end]);
  const totalMs = visibleIntervals.reduce((sum, item) => sum + item.visibleEnd - item.visibleStart, 0);
  const ticks = Array.from({ length: 5 }, (_, index) => start + (span * index) / 4);

  function pointerRatio(event: ReactPointerEvent<HTMLDivElement>) {
    const bounds = timelineRef.current?.getBoundingClientRect();
    if (!bounds) return 0;
    return Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || !timeline) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const ratio = pointerRatio(event);
    setSelection({ anchor: ratio, current: ratio });
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!selection) return;
    setSelection({ ...selection, current: pointerRatio(event) });
  }

  function handlePointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    if (!selection) return;
    const current = pointerRatio(event);
    const low = Math.min(selection.anchor, current);
    const high = Math.max(selection.anchor, current);
    setSelection(null);
    if (high - low < 0.02) return;
    setZoom({ start: start + span * low, end: start + span * high });
  }

  return <Card>
    <CardHeader>
      <CardTitle>{sensor.location_label} {sensor.kind === "door" ? "Door" : "Vibration"}</CardTitle>
      <CardDescription>{visibleIntervals.length} events · {Math.round(totalMs / 60000)} active minutes{zoom ? " · Temporary zoom" : ""}{sensor.current ? ` · Last reading: ${new Date(sensor.current.updated_at).toLocaleString()}` : ""}</CardDescription>
    </CardHeader>
    <CardContent>
      <div
        ref={timelineRef}
        className="relative h-12 touch-none select-none overflow-hidden rounded-md bg-muted cursor-crosshair"
        aria-label={`${sensor.label} activity timeline. Drag to zoom; double click to reset.`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={() => setSelection(null)}
        onDoubleClick={() => { setZoom(null); setSelection(null); }}
      >
        {visibleIntervals.map((item, index) => {
          const left = ((item.visibleStart - start) / span) * 100;
          const width = Math.max(0.35, ((item.visibleEnd - item.visibleStart) / span) * 100);
          return <div
            key={`${item.start}-${index}`}
            className="absolute inset-y-0 min-w-[6px] rounded-sm bg-emerald-500"
            style={{ left: `min(${left}%, calc(100% - 6px))`, width: `${width}%` }}
            title={`${new Date(item.start).toLocaleString()} – ${item.active ? "Active now" : new Date(item.end).toLocaleString()}`}
          />;
        })}
        {selection && <div
          className="pointer-events-none absolute inset-y-0 border border-primary bg-primary/20"
          style={{ left: `${Math.min(selection.anchor, selection.current) * 100}%`, width: `${Math.abs(selection.current - selection.anchor) * 100}%` }}
        />}
      </div>
      <div className="mt-2 grid grid-cols-5 text-[10px] text-muted-foreground">
        {ticks.map((tick, index) => <span key={tick} className={index === 0 ? "text-left" : index === ticks.length - 1 ? "text-right" : "text-center"}>{timeline ? formatTick(tick, span) : index === 0 ? "Loading…" : ""}</span>)}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">Drag to zoom{zoom ? " · Double-click to return to the page range" : ""}</p>
    </CardContent>
  </Card>;
}
