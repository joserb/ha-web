import { useEffect, useState } from "react";
import { fetchTrendSeries } from "@/lib/api";
import type { TimeRange } from "@/lib/ranges";
import type { Sensor, TrendSeries } from "@/types/sensors";

export function useTrends(sensors: Sensor[], range: TimeRange) {
  const [series, setSeries] = useState<TrendSeries[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = sensors.map((sensor) => sensor.id).join(",");

  useEffect(() => {
    if (!sensors.length) {
      setSeries([]);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    fetchTrendSeries(sensors, range)
      .then((value) => { if (active) setSeries(value); })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Unable to load trend data");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [key, range]);

  return { series, loading, error };
}
