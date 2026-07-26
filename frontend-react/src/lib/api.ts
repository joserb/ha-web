import type { HistoryPoint, Sensor, TrendSeries } from "@/types/sensors";
import type { TimeRange } from "@/lib/ranges";

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

export async function fetchSensors(signal?: AbortSignal): Promise<Sensor[]> {
  return json(await fetch("/api/sensors", { signal }));
}

export async function fetchTrendSeries(sensors: Sensor[], range: TimeRange): Promise<TrendSeries[]> {
  return Promise.all(sensors.map(async (sensor) => {
    const query = new URLSearchParams({
      location: sensor.location,
      measurement: sensor.measurement,
      range,
    });
    const points = await json<HistoryPoint[]>(await fetch(`/api/history?${query}`));
    return { sensor, points };
  }));
}
