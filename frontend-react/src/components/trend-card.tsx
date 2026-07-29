import { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useTrends } from "@/hooks/use-trends";
import type { TimeRange } from "@/lib/ranges";
import type { Sensor } from "@/types/sensors";

const colors = ["#22c55e", "#3b82f6", "#f97316", "#a855f7", "#06b6d4", "#eab308"];

export function TrendCard({ title, sensors, range }: { title: string; sensors: Sensor[]; range: TimeRange }) {
  const { series, loading, error } = useTrends(sensors, range);
  const [hiddenChannels, setHiddenChannels] = useState<Set<string>>(() => new Set());
  const data = useMemo(() => {
    const rows = new Map<string, Record<string, string | number>>();
    for (const item of series) {
      for (const point of item.points) {
        const row = rows.get(point.time) ?? { time: point.time };
        row[item.sensor.id] = point.value;
        rows.set(point.time, row);
      }
    }
    return [...rows.values()].sort((a, b) => String(a.time).localeCompare(String(b.time)));
  }, [series]);
  const unit = sensors[0]?.unit ?? "";
  const latest = sensors.reduce<Date | null>((result, sensor) => {
    if (!sensor.current) return result;
    const date = new Date(sensor.current.updated_at);
    return result === null || date > result ? date : result;
  }, null);

  function toggleChannel(sensorId: string) {
    setHiddenChannels((current) => {
      const next = new Set(current);
      if (next.has(sensorId)) next.delete(sensorId);
      else next.add(sensorId);
      return next;
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{sensors.length} channels · {range}{latest ? ` · Last reading: ${latest.toLocaleString()}` : ""}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="h-64">
          {loading ? <div className="grid h-full place-items-center text-sm text-muted-foreground">Loading trend…</div>
            : error ? <div className="grid h-full place-items-center text-sm text-destructive">{error}</div>
              : data.length === 0 ? <div className="grid h-full place-items-center text-sm text-muted-foreground">No data for this period</div>
                : <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
                    <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                    <XAxis dataKey="time" tickFormatter={(value) => new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} tick={{ fill: "var(--muted-foreground)", fontSize: 10 }} minTickGap={48} />
                    <YAxis unit={unit} tick={{ fill: "var(--muted-foreground)", fontSize: 10 }} width={52} domain={title === "Battery" ? [0, 100] : ["auto", "auto"]} />
                    <Tooltip labelFormatter={(value) => new Date(String(value)).toLocaleString()} formatter={(value, name) => [`${Number(value).toFixed(1)}${unit}`, sensors.find((sensor) => sensor.id === name)?.location_label ?? name]} />
                    {sensors.map((sensor, index) => <Line key={sensor.id} dataKey={sensor.id} type="monotone" stroke={colors[index % colors.length]} dot={false} strokeWidth={2} connectNulls isAnimationActive={false} hide={hiddenChannels.has(sensor.id)} />)}
                  </LineChart>
                </ResponsiveContainer>}
        </div>
        {!loading && !error && data.length > 0 && <div className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-2" aria-label={`${title} channels`}>
          {sensors.map((sensor, index) => {
            const hidden = hiddenChannels.has(sensor.id);
            return <button
              key={sensor.id}
              type="button"
              className={`flex items-center gap-1.5 text-xs transition-opacity ${hidden ? "opacity-40 line-through" : "opacity-100"}`}
              onClick={() => toggleChannel(sensor.id)}
              aria-pressed={!hidden}
              title={`${hidden ? "Show" : "Hide"} ${sensor.location_label}`}
            >
              <span className="inline-block h-0.5 w-4" style={{ backgroundColor: colors[index % colors.length] }} />
              {sensor.location_label}
            </button>;
          })}
        </div>}
      </CardContent>
    </Card>
  );
}
