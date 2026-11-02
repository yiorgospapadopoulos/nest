import type { PerfMetric, PerfUnit } from "../../api/types.ts";

/**
 * Each metric's two bars (previous run, this run) as percents of the longest bar among the
 * section's metrics of the same unit, so seconds are compared with seconds only (B115).
 */
export function barWidths(metrics: PerfMetric[]): Map<string, { previous: number; value: number }> {
  // A share is drawn against the whole: 13% of the context window is a short bar.
  const largest = new Map<PerfUnit, number>([["percent", 100]]);
  for (const m of metrics) {
    const top = Math.max(m.value ?? 0, m.previous ?? 0);
    largest.set(m.unit, Math.max(largest.get(m.unit) ?? 0, top));
  }
  const share = (n: number | null, of: number) =>
    n === null || of <= 0 ? 0 : (100 * Math.max(0, n)) / of;
  return new Map(
    metrics.map((m) => {
      const of = largest.get(m.unit) ?? 0;
      return [m.id, { previous: share(m.previous, of), value: share(m.value, of) }];
    }),
  );
}

/** "42 s", "1 min 42 s", "3 min": how long a run took. */
export function durationText(ms: number): string {
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${String(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0 ? `${String(minutes)} min` : `${String(minutes)} min ${String(rest)} s`;
}
