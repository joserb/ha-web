import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Sensor } from "@/types/sensors";

function point(angle: number, radius = 82) {
  const radians = (angle * Math.PI) / 180;
  return { x: 110 + radius * Math.cos(radians), y: 105 + radius * Math.sin(radians) };
}

function angleFor(value: number) {
  const clamped = Math.max(10, Math.min(36, value));
  return 180 + ((clamped - 10) / 26) * 180;
}

function arc(start: number, end: number) {
  const from = point(angleFor(start));
  const to = point(angleFor(end));
  return `M ${from.x} ${from.y} A 82 82 0 0 1 ${to.x} ${to.y}`;
}

export function TemperatureMeterCard({ sensor }: { sensor: Sensor }) {
  const value = Number(sensor.current?.payload);
  const valid = Number.isFinite(value);
  const needle = point(valid ? angleFor(value) : 180, 62);
  const readAt = sensor.current ? new Date(sensor.current.updated_at) : null;

  return (
    <Card className={sensor.current?.stale ? "border-amber-500/70" : undefined}>
      <CardHeader className="pb-1 text-center">
        <CardTitle>{sensor.location_label}</CardTitle>
        <CardDescription>Temperature</CardDescription>
      </CardHeader>
      <CardContent>
        <svg viewBox="0 0 220 135" className="mx-auto w-full max-w-72" role="img" aria-label={`${sensor.location_label} temperature ${valid ? `${value.toFixed(1)} degrees Celsius` : "unavailable"}`}>
          <defs>
            <linearGradient id={`temperature-gradient-${sensor.id}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#1e3a8a" />
              <stop offset="23%" stopColor="#38bdf8" />
              <stop offset="50%" stopColor="#22c55e" />
              <stop offset="65%" stopColor="#facc15" />
              <stop offset="80%" stopColor="#f97316" />
              <stop offset="100%" stopColor="#dc2626" />
            </linearGradient>
          </defs>
          <path d={arc(10, 36)} fill="none" stroke={`url(#temperature-gradient-${sensor.id})`} strokeWidth="18" strokeLinecap="butt" />
          <line x1="110" y1="105" x2={needle.x} y2={needle.y} stroke="currentColor" strokeWidth="4" strokeLinecap="round" className="transition-all motion-reduce:transition-none" />
          <circle cx="110" cy="105" r="7" fill="currentColor" />
          <text x="110" y="82" textAnchor="middle" className="fill-current text-[28px] font-semibold tabular-nums">
            {valid ? value.toFixed(1) : "—"}
          </text>
          <text x="110" y="100" textAnchor="middle" className="fill-muted-foreground text-[11px]">°C</text>
          <text x="22" y="124" textAnchor="middle" className="fill-muted-foreground text-[9px]">10</text>
          <text x="110" y="13" textAnchor="middle" className="fill-muted-foreground text-[9px]">23</text>
          <text x="198" y="124" textAnchor="middle" className="fill-muted-foreground text-[9px]">36</text>
        </svg>
        <p className={`text-center text-xs ${sensor.current?.stale ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}`}>
          {readAt ? <><span className="font-medium">Last reading:</span>{" "}<time dateTime={sensor.current!.updated_at}>{readAt.toLocaleString()}</time>{sensor.current?.stale ? " · Stale" : ""}</> : "No current reading"}
        </p>
      </CardContent>
    </Card>
  );
}
