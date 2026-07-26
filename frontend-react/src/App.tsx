import { useState } from "react";
import { DashboardHeader } from "@/components/dashboard-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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

  function setRange(value: TimeRange) {
    localStorage.setItem("ha-web.time-range", value);
    setRangeState(value);
  }

  return (
    <main className="mx-auto min-h-screen max-w-[1600px] p-4 sm:p-6 lg:p-8">
      <DashboardHeader
        connected={false}
        range={range}
        onRangeChange={setRange}
        theme={theme}
        onThemeChange={setTheme}
      />
      <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Dashboard foundation ready</CardTitle>
            <CardDescription>Sensor cards will be connected in the next implementation slice.</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            React 19, Tailwind CSS v4 and project-owned shadcn/ui components are active.
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
