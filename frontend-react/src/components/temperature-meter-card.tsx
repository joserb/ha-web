import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Sensor } from "@/types/sensors";

const zones = [
  [-5, 10, "#1d4ed8"],
  [10, 16, "#3b82f6"],
  [16, 20, "#7dd3fc"],
  [20, 23, "#22c55e"],
  [23, 26, "#facc15"],
  [26, 30, "#f97316"],
  [30, 45, "#ef4444"],
] as const;

function point(angle: number, radius = 82) {
  const radians = (angle * Math.PI) / 180;
  return { x: 110 + radius * Math.cos(radians), y: 105 + radius * Math.sin(radians) };
}

function angleFor(value: number) {
  const clamped = Math.max(-5, Math.min(45, value));
  return 210 + ((clamped + 5) / 50) * 240;
}

function arc(start: number, end: number) {
  const from = point(angleFor(start));
  const to = point(angleFor(end));
  return `M ${from.x} ${from.y} A 82 82 0 0 1 ${to.x} ${to.y}`;
}

function formatAge(seconds: number) {
  if (seconds < 60) return "Updated just now";
  if (seconds < 3600) return `Updated ${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `Updated ${Math.floor(seconds / 3600)} h ago`;
  return `Updated ${Math.floor(seconds / 86400)} d ago`;
}

export function TemperatureMeterCard({ sensor }: { sensor: Sensor }) {
  const value = Number(sensor.current?.payload);
  const valid = Number.isFinite(value);
  const needle = point(valid ? angleFor(value) : 210, 62);

  return (
    <Card className={sensor.current?.stale ? "border-amber-500/70" : undefined}>
      <CardHeader className="pb-1 text-center">
        <CardTitle>{sensor.location_label}</CardTitle>
        <CardDescription>Temperature</CardDescription>
      </CardHeader>
      <CardContent>
        <svg viewBox="0 0 220 145" className="mx-auto w-full max-w-72" role="img" aria-label={`${sensor.location_label} temperature ${valid ? `${value.toFixed(1)} degrees Celsius` : "unavailable"}`}>
          {zones.map(([start, end, color]) => (
            <path key={start} d={arc(start, end)} fill="none" stroke={color} strokeWidth="18" strokeLinecap="butt" />
          ))}
          <line x1="110" y1="105" x2={needle.x} y2={needle.y} stroke="currentColor" strokeWidth="4" strokeLinecap="round" className="transition-all motion-reduce:transition-none" />
          <circle cx="110" cy="105" r="7" fill="currentColor" />
          <text x="110" y="82" textAnchor="middle" className="fill-current text-[28px] font-semibold tabular-nums">
            {valid ? value.toFixed(1) : "—"}
          </text>
          <text x="110" y="100" textAnchor="middle" className="fill-muted-foreground text-[11px]">°C</text>
          <text x="22" y="132" textAnchor="middle" className="fill-muted-foreground text-[9px]">−5</text>
          <text x="198" y="132" textAnchor="middle" className="fill-muted-foreground text-[9px]">45</text>
        </svg>
        <p className={`text-center text-xs ${sensor.current?.stale ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}`}>
          {sensor.current ? `${sensor.current.stale ? "Stale · " : ""}${formatAge(sensor.current.age_seconds)}` : "No current reading"}
        </p>
      </CardContent>
    </Card>
  );
}
