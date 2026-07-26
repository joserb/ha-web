import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { TimeRange } from "@/lib/ranges";
import type { Sensor } from "@/types/sensors";

interface Timeline { range_start: string; range_end: string; intervals: Array<{ start: string; end: string; active: boolean }> }

export function EventTimelineCard({ sensor, range }: { sensor: Sensor; range: TimeRange }) {
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const latestReading = sensor.current?.updated_at;
  useEffect(() => {
    const query = new URLSearchParams({ sensor_id: sensor.id, range });
    fetch(`/api/intervals?${query}`).then((response) => response.json()).then(setTimeline).catch(() => setTimeline(null));
  }, [sensor.id, range, latestReading]);
  const start = timeline ? new Date(timeline.range_start).getTime() : 0;
  const end = timeline ? new Date(timeline.range_end).getTime() : 1;
  const span = Math.max(1, end - start);
  const totalMs = timeline?.intervals.reduce((sum, item) => sum + new Date(item.end).getTime() - new Date(item.start).getTime(), 0) ?? 0;

  return <Card>
    <CardHeader>
      <CardTitle>{sensor.location_label} {sensor.kind === "door" ? "Door" : "Vibration"}</CardTitle>
      <CardDescription>{timeline?.intervals.length ?? 0} events · {Math.round(totalMs / 60000)} active minutes{sensor.current ? ` · Last reading: ${new Date(sensor.current.updated_at).toLocaleString()}` : ""}</CardDescription>
    </CardHeader>
    <CardContent>
      <div className="relative h-10 overflow-hidden rounded-md bg-muted" aria-label={`${sensor.label} activity timeline`}>
        {timeline?.intervals.map((item, index) => {
          const left = ((new Date(item.start).getTime() - start) / span) * 100;
          const width = Math.max(0.35, ((new Date(item.end).getTime() - new Date(item.start).getTime()) / span) * 100);
          return <div key={`${item.start}-${index}`} className="absolute inset-y-0 rounded-sm bg-emerald-500" style={{ left: `${left}%`, width: `${width}%` }} title={`${new Date(item.start).toLocaleString()} – ${item.active ? "Active now" : new Date(item.end).toLocaleString()}`} />;
        })}
      </div>
      <div className="mt-2 flex justify-between text-xs text-muted-foreground"><span>{timeline ? new Date(timeline.range_start).toLocaleString() : "Loading…"}</span><span>Now</span></div>
    </CardContent>
  </Card>;
}
