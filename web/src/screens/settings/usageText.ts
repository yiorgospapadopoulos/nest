import type { PeriodUnit, ProjectUsage, UsageBar, UsagePeriod } from "../../api/types.ts";
import { isoDay, monthName, tokens } from "../../format.ts";

// The usage detail's periods and numbers (B84), titled and written as the Mac writes them.

export const UNITS: readonly { value: PeriodUnit; label: string }[] = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "year", label: "Year" },
];

// The tallest bar, in pixels, and the least a bar with any tokens gets.
const BAR_MAX = 64;
const BAR_MIN = 3;
// Projects shown by name in the breakdown; the rest are one "Others" row.
const TOP_PROJECTS = 4;

// Kept here for the Usage screens; the store reads it from format.ts.
export { isoDay };

// Noon, so a daylight saving change never moves the day.
function day(iso: string): Date {
  return new Date(`${iso}T12:00:00`);
}

function shifted(iso: string, days: number): string {
  const at = day(iso);
  at.setDate(at.getDate() + days);
  return isoDay(at);
}

/** The first and last day of the `unit` holding `date`; weeks start on Monday. */
export function periodRange(unit: PeriodUnit, date: string): { start: string; end: string } {
  const at = day(date);
  const year = at.getFullYear();
  if (unit === "day") return { start: date, end: date };
  if (unit === "week") {
    const start = shifted(date, -((at.getDay() + 6) % 7));
    return { start, end: shifted(start, 6) };
  }
  if (unit === "month") {
    const month = at.getMonth();
    return {
      start: isoDay(new Date(year, month, 1, 12)),
      end: isoDay(new Date(year, month + 1, 0, 12)),
    };
  }
  return { start: `${String(year)}-01-01`, end: `${String(year)}-12-31` };
}

/** A day in the period before (`-1`) or after (`1`) the one holding `date`. */
export function stepDate(unit: PeriodUnit, date: string, step: -1 | 1): string {
  const { start, end } = periodRange(unit, date);
  return step === -1 ? shifted(start, -1) : shifted(end, 1);
}

// Fixed short names, as the Mac's UsageText writes them (the browser's en-GB says "Sept").
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** "16 Oct". */
const dayMonth = (at: Date) => `${String(at.getDate())} ${String(MONTHS[at.getMonth()])}`;
/** "Fri 16 Oct". */
const weekday = (at: Date) => `${String(WEEKDAYS[at.getDay()])} ${dayMonth(at)}`;

/** "Today", "Fri 16 Oct", "12 to 18 Oct", "October", "October 2025" or "2026". */
export function periodTitle(unit: PeriodUnit, date: string, today: Date): string {
  const at = day(date);
  if (unit === "day") return date === isoDay(today) ? "Today" : weekday(at);
  if (unit === "week") {
    const { start, end } = periodRange(unit, date);
    const first = day(start);
    const last = day(end);
    const from = first.getMonth() === last.getMonth() ? String(first.getDate()) : dayMonth(first);
    return `${from} to ${dayMonth(last)}`;
  }
  const year = String(at.getFullYear());
  if (unit === "year") return year;
  const month = monthName(at.getMonth() + 1);
  return at.getFullYear() === today.getFullYear() ? month : `${month} ${year}`;
}

/** The labels under the bars, spread from the first to the last. */
export function ticks(unit: PeriodUnit, date: string): string[] {
  if (unit === "day") return ["0", "6", "12", "18", "23"];
  if (unit === "week") return ["Mo", "We", "Fr", "Su"];
  if (unit === "year") return ["Jan", "Apr", "Jul", "Oct", "Dec"];
  const last = String(Number(periodRange(unit, date).end.slice(8)));
  return ["1", "8", "15", "22", last];
}

/** "3 chats", "1 chat". */
export function chatCount(n: number): string {
  return `${String(n)} chat${n === 1 ? "" : "s"}`;
}

/** "Wed 14 Oct: 3.4M tokens, 12 chats"; an hour reads "14:00", a month "October". */
export function barTip(unit: PeriodUnit, bar: UsageBar): string {
  // The start's own wall clock, whatever this phone's time zone is.
  const date = bar.start.slice(0, 10);
  const when =
    unit === "day"
      ? `${bar.start.slice(11, 13)}:00`
      : unit === "year"
        ? monthName(Number(date.slice(5, 7)))
        : weekday(day(date));
  return `${when}: ${tokens(bar.tokens)} tokens, ${chatCount(bar.sessions)}`;
}

/** A bar's height in pixels against the busiest bar; an empty one is a 1 pixel line. */
export function barHeight(value: number, peak: number): number {
  if (value <= 0 || peak <= 0) return 1;
  return Math.max(BAR_MIN, Math.round((BAR_MAX * value) / peak));
}

/** "89%", "0.7%", "0.01%": a part of the total, small ones with more digits. */
export function share(part: number, total: number): string {
  if (part <= 0 || total <= 0) return "0%";
  const value = (100 * part) / total;
  if (value >= 1) return `${String(Math.round(value))}%`;
  if (value >= 0.1) return `${value.toFixed(1)}%`;
  return value >= 0.005 ? `${value.toFixed(2)}%` : "<0.01%";
}

/** The top projects by tokens, then the rest as one "Others (n)" row. */
export function projectRows(projects: ProjectUsage[]): { name: string; tokens: number }[] {
  const top = projects.slice(0, TOP_PROJECTS).map((p) => ({ name: p.name, tokens: p.tokens }));
  const rest = projects.slice(TOP_PROJECTS);
  if (rest.length === 0) return top;
  const others = rest.reduce((sum, p) => sum + p.tokens, 0);
  return [...top, { name: `Others (${String(rest.length)})`, tokens: others }];
}

/** "12 usage checks, 5k tokens, not counted above", or null when there were none. */
export function probesLine(probes: UsagePeriod["probes"]): string | null {
  if (probes.count === 0) return null;
  const checks = `${String(probes.count)} usage check${probes.count === 1 ? "" : "s"}`;
  return `${checks}, ${tokens(probes.tokens)} tokens, not counted above`;
}
