/**
 * Derives the recent-events log from the intervals the timeline already has.
 *
 * Kept out of the card because this is the only part with real logic — order,
 * clipping, duration, an event still in progress — and a pure function can be
 * checked without rendering anything.
 */

/** Above this span the timeline labels carry a date, not just a time. */
export const LONG_SPAN_MS = 36 * 60 * 60 * 1000;

export interface VisibleInterval {
  start: string;
  end: string;
  active: boolean;
  visibleStart: number;
  visibleEnd: number;
}

export interface TimelineEvent {
  start: number;
  durationMs: number;
  /** Still happening: the interval is open and the window does not cut its end. */
  ongoing: boolean;
  /** Began before the window, so its real start is unknown from here. */
  clippedStart: boolean;
}

export function recentEvents(intervals: VisibleInterval[], limit: number, now: number): TimelineEvent[] {
  return intervals
    .map((interval) => {
      const clippedEnd = interval.visibleEnd < new Date(interval.end).getTime();
      const ongoing = interval.active && !clippedEnd;
      return {
        start: interval.visibleStart,
        // An open interval ends "now", not when the response was built, so the
        // duration has to keep moving between fetches.
        durationMs: ongoing
          ? Math.max(0, now - interval.visibleStart)
          : interval.visibleEnd - interval.visibleStart,
        ongoing,
        clippedStart: interval.visibleStart > new Date(interval.start).getTime(),
      };
    })
    .sort((a, b) => b.start - a.start)
    .slice(0, limit);
}

export function formatDuration(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return seconds % 60 ? `${minutes}m ${seconds % 60}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return minutes % 60 ? `${hours}h ${minutes % 60}m` : `${hours}h`;
  const days = Math.floor(hours / 24);
  return hours % 24 ? `${days}d ${hours % 24}h` : `${days}d`;
}

/** Unlike the axis ticks, an event keeps its seconds: it is a fact, not a scale. */
export function formatEventTime(value: number, span: number): string {
  const date = new Date(value);
  const time = { hour: "2-digit", minute: "2-digit", second: "2-digit" } as const;
  return span > LONG_SPAN_MS
    ? date.toLocaleString([], { month: "short", day: "numeric", ...time })
    : date.toLocaleTimeString([], time);
}
