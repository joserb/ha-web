export const timeRanges = [
  ["1h", "1 hour"],
  ["6h", "6 hours"],
  ["12h", "12 hours"],
  ["1d", "1 day"],
  ["7d", "7 days"],
  ["30d", "30 days"],
  ["3m", "3 months"],
  ["6m", "6 months"],
  ["1y", "1 year"],
  ["forever", "All time"],
] as const;

export type TimeRange = (typeof timeRanges)[number][0];
