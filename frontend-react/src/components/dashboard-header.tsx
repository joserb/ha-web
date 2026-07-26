import { Activity, MonitorCog, Moon, Sun } from "lucide-react";
import type { ThemePreference } from "@/hooks/use-theme";
import { timeRanges, type TimeRange } from "@/lib/ranges";

interface DashboardHeaderProps {
  connected: boolean;
  range: TimeRange;
  onRangeChange: (range: TimeRange) => void;
  theme: ThemePreference;
  onThemeChange: (theme: ThemePreference) => void;
}

const themes: Array<[ThemePreference, string]> = [
  ["system", "System"],
  ["light", "Light"],
  ["dark", "Dark"],
];

export function DashboardHeader(props: DashboardHeaderProps) {
  const ThemeIcon = props.theme === "light" ? Sun : props.theme === "dark" ? Moon : MonitorCog;
  return (
    <header className="flex flex-col gap-4 border-b pb-5 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <div className="flex items-center gap-2">
          <Activity className="size-5 text-primary" aria-hidden="true" />
          <h1 className="text-xl font-semibold tracking-tight">Home Sensors</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">Live conditions from pihomeblk-1</p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          Time range
          <select
            className="h-9 rounded-md border bg-background px-3 text-sm text-foreground shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
            value={props.range}
            onChange={(event) => props.onRangeChange(event.target.value as TimeRange)}
          >
            {timeRanges.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          Theme
          <span className="relative">
            <ThemeIcon className="pointer-events-none absolute left-2.5 top-2.5 size-4" aria-hidden="true" />
            <select
              className="h-9 rounded-md border bg-background pl-9 pr-3 text-sm text-foreground shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={props.theme}
              onChange={(event) => props.onThemeChange(event.target.value as ThemePreference)}
            >
              {themes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </span>
        </label>
        <div className="mt-5 flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <span className={`size-2 rounded-full ${props.connected ? "bg-emerald-500" : "bg-destructive"}`} />
          {props.connected ? "Live" : "Disconnected"}
        </div>
      </div>
    </header>
  );
}
