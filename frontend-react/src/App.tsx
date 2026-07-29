import { useState } from "react";
import { DashboardHeader } from "@/components/dashboard-header";
import { TemperatureMeterCard } from "@/components/temperature-meter-card";
import { TrendCard } from "@/components/trend-card";
import { EventTimelineCard } from "@/components/event-timeline-card";
import { useDashboardData } from "@/hooks/use-dashboard-data";
import { useTheme } from "@/hooks/use-theme";
import type { TimeRange } from "@/lib/ranges";

function initialRange(): TimeRange {
  const value = localStorage.getItem("ha-web.time-range");
  const valid = ["1h", "6h", "12h", "1d", "7d", "30d", "3m", "6m", "1y", "forever"];
  return valid.includes(value ?? "") ? value as TimeRange : "1d";
}

export default function App() {
  const [range, setRangeState] = useState<TimeRange>(initialRange);
  const { theme, setTheme } = useTheme();
  const { sensors, loading, error, connected } = useDashboardData();

  function setRange(value: TimeRange) {
    localStorage.setItem("ha-web.time-range", value);
    setRangeState(value);
  }

  return (
    <main className="mx-auto min-h-screen max-w-[1600px] p-4 sm:p-6 lg:p-8">
      <DashboardHeader
        connected={connected}
        range={range}
        onRangeChange={setRange}
        theme={theme}
        onThemeChange={setTheme}
      />
      {loading && <p className="mt-8 text-sm text-muted-foreground">Loading sensors…</p>}
      {error && <p className="mt-8 text-sm text-destructive">Unable to load sensors: {error}</p>}
      {!loading && !error && <>
        <section className="mt-6" aria-labelledby="temperature-heading">
          <h2 id="temperature-heading" className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">Temperature</h2>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {sensors.filter((sensor) => sensor.kind === "temperature").map((sensor) => <TemperatureMeterCard key={sensor.id} sensor={sensor} />)}
          </div>
        </section>
        <section className="mt-8 space-y-4" aria-labelledby="trends-heading">
          <h2 id="trends-heading" className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Trends</h2>
          {[["Temperature", "temperatures"], ["Humidity", "humidities"], ["Pressure", "pressures"], ["Battery", "batteries"]].map(([title, family]) => {
            const familySensors = sensors.filter((sensor) => sensor.family === family);
            return familySensors.length ? <TrendCard key={family} title={title} sensors={familySensors} range={range} /> : null;
          })}
        </section>
        <section className="mt-8 space-y-4" aria-labelledby="events-heading">
          <h2 id="events-heading" className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Activity timelines</h2>
          <div className="grid gap-4 lg:grid-cols-2">
            {sensors.filter((sensor) => sensor.card === "timeline").map((sensor) => <EventTimelineCard key={sensor.id} sensor={sensor} range={range} />)}
          </div>
        </section>
      </>}
    </main>
  );
}
