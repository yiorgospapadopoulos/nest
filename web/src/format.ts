/** Short display formats shared by the screens. */

const MINUTE = 60_000;

/** "now", "5m", "2h 5m", "3d": how long ago `iso` was. */
export function ago(iso: string, now: Date): string {
  const minutes = Math.floor((now.getTime() - new Date(iso).getTime()) / MINUTE);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${String(minutes)}m`;
  if (minutes < 1440) {
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return rest ? `${String(hours)}h ${String(rest)}m` : `${String(hours)}h`;
  }
  return `${String(Math.floor(minutes / 1440))}d`;
}

/** 950, 12k, 1.4M, 3M */
export function tokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${String(Math.round(n / 1000))}k`;
  const millions = (n / 1_000_000).toFixed(1);
  return `${millions.endsWith(".0") ? millions.slice(0, -2) : millions}M`;
}

export function percent(fraction: number): number {
  return Math.round(Math.min(1, Math.max(0, fraction)) * 100);
}

/** "18:30" in the local time zone. */
export function clockTime(at: Date): string {
  return at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/** "Resets 18:30" today, otherwise "Resets Mon 09:00". */
export function resetLabel(iso: string | null, now: Date): string {
  if (iso === null) return "Reset time unknown";
  const at = new Date(iso);
  const time = clockTime(at);
  if (at.toDateString() === now.toDateString()) return `Resets ${time}`;
  const day = at.toLocaleDateString("en-GB", { weekday: "short" });
  return `Resets ${day} ${time}`;
}

/** "October" for 10. */
export function monthName(month: number): string {
  return new Date(2000, month - 1, 1).toLocaleDateString("en-GB", { month: "long" });
}

/** Up to two initials for a project badge: "todo-ui" reads "TU". */
export function initials(name: string): string {
  const words = name.split(/[^A-Za-z0-9]+/).filter(Boolean);
  const first = words[0]?.[0] ?? "?";
  const second = words[1]?.[0] ?? "";
  return (first + second).toUpperCase();
}

/** "#7" from a pull request URL, or "PR" when it has no number. */
export function prLabel(url: string): string {
  const number = /\/pull\/(\d+)/.exec(url)?.[1];
  return number === undefined ? "PR" : `#${number}`;
}
