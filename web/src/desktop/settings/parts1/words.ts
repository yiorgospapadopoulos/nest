// The words of Settings' General to Features pages, as NestKit writes them: UsageText's
// refresh and warning choices, StuckThreshold, StorageText, PerfText and the Features
// intro. Pure, so the rules are tested without a DOM.
import type { StorageUsage, StoredAttachment, StuckSettings } from "../../../api/types.ts";

// MARK: Usage

/** The refresh intervals offered, in minutes; 0 is off. */
export const REFRESH_CHOICES = [0, 1, 3, 5, 10, 15];

/** "Off", "Every minute", "Every 3 minutes"; "-" before the setting loaded. */
export function refreshInterval(minutes: number | null): string {
  if (minutes === null) return "-";
  if (minutes === 0) return "Off";
  return minutes === 1 ? "Every minute" : `Every ${String(minutes)} minutes`;
}

/** The warning levels offered, in percent; null is off. */
export const WARN_CHOICES: (number | null)[] = [70, 80, 90, null];

/** "80%", or "Off". */
export function warnLevel(percent: number | null): string {
  return percent === null ? "Off" : `${String(percent)}%`;
}

const two = (n: number) => String(n).padStart(2, "0");

/** The ids with `id` moved up (-1) or down (1) by one, as Alt and the arrow keys move it. */
export function movedBy(ids: string[], id: string, by: -1 | 1): string[] {
  const from = ids.indexOf(id);
  const to = from + by;
  if (from === -1 || to < 0 || to >= ids.length) return ids;
  const next = [...ids];
  next.splice(from, 1);
  next.splice(to, 0, id);
  return next;
}

/** Where a dragged row lands: its start moved by whole rows, inside the list. */
export function dragTarget(from: number, translation: number, step: number, count: number) {
  if (step <= 0) return from;
  return Math.max(0, Math.min(count - 1, from + Math.round(translation / step)));
}

/** How far a row slides while another is dragged from `from` to `to`. */
export function dragOffset(index: number, from: number, to: number, step: number): number {
  if (from < index && index <= to) return -step;
  if (to <= index && index < from) return step;
  return 0;
}

// MARK: Stuck chats

export interface StuckThreshold {
  key: keyof StuckSettings;
  title: string;
  base: number[];
}

/** When the daemon flags a running chat as stuck (D036), in the Mac's order and words. */
export const STUCK_THRESHOLDS: StuckThreshold[] = [
  { key: "waiting_minutes", title: "Waiting on a prompt", base: [0, 5, 10, 15, 20, 30, 45, 60] },
  { key: "silent_minutes", title: "No new output", base: [0, 5, 10, 15, 20, 30, 45, 60] },
  { key: "repeated_calls", title: "Same call repeated", base: [0, 3, 4, 5, 6, 8, 10] },
  { key: "turn_minutes", title: "One turn running", base: [0, 30, 45, 60, 90, 120, 180] },
];

/** The menu's values, with the current one added in order when it is not among them. */
export function stuckChoices(threshold: StuckThreshold, current: number): number[] {
  const { base } = threshold;
  return base.includes(current) ? base : [...base, current].sort((a, b) => a - b);
}

/** "Off", "15 minutes", "1 hour 30 minutes" or "More than 4 times". */
export function stuckLabel(threshold: StuckThreshold, value: number): string {
  if (value <= 0) return "Off";
  if (threshold.key === "repeated_calls") return `More than ${String(value)} times`;
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  const hourText = hours === 1 ? "1 hour" : `${String(hours)} hours`;
  const minuteText = minutes === 1 ? "1 minute" : `${String(minutes)} minutes`;
  if (hours === 0) return minuteText;
  return minutes === 0 ? hourText : `${hourText} ${minuteText}`;
}

// MARK: Storage

/** "540 bytes", "12 KB", "820 MB", "1.4 GB"; in thousands, as Finder counts. */
export function bytes(count: number): string {
  if (count < 1_000) return `${String(count)} bytes`;
  if (count < 1_000_000) return `${String(Math.round(count / 1_000))} KB`;
  if (count < 1_000_000_000) return `${String(Math.round(count / 1_000_000))} MB`;
  return `${(count / 1_000_000_000).toFixed(1)} GB`;
}

export type StoragePart =
  "chats" | "attachments" | "artifacts" | "engines" | "backups" | "logs" | "other";

export const PART_NAMES: Record<StoragePart, string> = {
  chats: "Chats",
  attachments: "Attachments",
  artifacts: "Artifacts",
  engines: "Engines",
  backups: "Backups",
  logs: "Logs",
  other: "Other",
};

function parts(usage: StorageUsage): { part: StoragePart; bytes: number }[] {
  return [
    { part: "chats", bytes: usage.chats_bytes },
    { part: "attachments", bytes: usage.attachments_bytes },
    { part: "artifacts", bytes: usage.artifacts_bytes },
    { part: "engines", bytes: usage.engines_bytes },
    { part: "backups", bytes: usage.backups_bytes },
    { part: "logs", bytes: usage.logs_bytes },
    { part: "other", bytes: usage.other_bytes },
  ];
}

/** Each part's share of the total, for the space used bar; none while it is empty. */
export function shares(usage: StorageUsage): { part: StoragePart; share: number }[] {
  if (usage.total_bytes <= 0) return [];
  return parts(usage).map(({ part, bytes: size }) => ({ part, share: size / usage.total_bytes }));
}

/** A share as a whole percent: "<1%" above zero but under 1%, "0%" at zero. */
export function shareText(share: number): string {
  if (share > 0 && share < 0.01) return "<1%";
  return `${String(Math.round(share * 100))}%`;
}

/** The ledger's lines (B86): each part with its size and share, all of them even at zero. */
export function ledger(usage: StorageUsage): { part: StoragePart; size: string; share: string }[] {
  const total = usage.total_bytes;
  return parts(usage).map(({ part, bytes: size }) => ({
    part,
    size: bytes(size),
    share: shareText(total > 0 ? size / total : 0),
  }));
}

/**
 * The bar's segments at a width: parts above zero, `gap` apart, none narrower than
 * `minimum`; the largest takes what the others leave, so they fill the width exactly.
 */
export function segments(
  list: { part: StoragePart; share: number }[],
  width: number,
  gap: number,
  minimum: number,
): { part: StoragePart; width: number }[] {
  const shown = list.filter((item) => item.share > 0);
  const largest = shown.reduce<(typeof shown)[number] | null>(
    (top, item) => (top === null || item.share > top.share ? item : top),
    null,
  );
  if (largest === null) return [];
  const available = width - gap * (shown.length - 1);
  const others = new Map(
    shown
      .filter((item) => item.part !== largest.part)
      .map((item) => [item.part, Math.max(minimum, item.share * available)]),
  );
  const rest = available - [...others.values()].reduce((sum, w) => sum + w, 0);
  return shown.map((item) => ({ part: item.part, width: others.get(item.part) ?? rest }));
}

/** Archive chats idle for: Never, 1, 2, 3, 7, 30 or 90 days. */
export const ARCHIVE_CHOICES: (number | null)[] = [null, 1, 2, 3, 7, 30, 90];

/** "Never", "1 day", "30 days". */
export function archiveLabel(days: number | null): string {
  if (days === null) return "Never";
  return days === 1 ? "1 day" : `${String(days)} days`;
}

/** Where an attachment came from: its chat, or none any more. */
export function attachmentSource(attachment: StoredAttachment): string {
  return attachment.session_title ?? (attachment.session_id === null ? "No chat" : "Untitled chat");
}

// MARK: Performance

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "today 10:58", "yesterday 18:02", "12 Oct 09:30". */
export function perfTime(at: Date, now: Date): string {
  const clock = `${two(at.getHours())}:${two(at.getMinutes())}`;
  if (at.toDateString() === now.toDateString()) return `today ${clock}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (at.toDateString() === yesterday.toDateString()) return `yesterday ${clock}`;
  return `${String(at.getDate())} ${String(MONTHS[at.getMonth()])} ${clock}`;
}

/** "1 min 42 s", "42 s", "0.8 s", "1 h 3 min". */
export function perfDuration(ms: number): string {
  if (ms < 10_000) return `${(ms / 1000).toFixed(1)} s`;
  const total = Math.round(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0)
    return minutes > 0 ? `${String(hours)} h ${String(minutes)} min` : `${String(hours)} h`;
  if (minutes > 0) {
    return seconds > 0 ? `${String(minutes)} min ${String(seconds)} s` : `${String(minutes)} min`;
  }
  return `${String(seconds)} s`;
}

/** "Last run today 10:58 · 1 min 42 s", "Running since 10:58" or "Not run yet". */
export function perfHeader(
  view: {
    running: { started_at: string } | null;
    last_run: { finished_at: string; duration_ms: number } | null;
  } | null,
  now: Date,
): string {
  if (view?.running != null) {
    return `Running since ${perfTime(new Date(view.running.started_at), now)}`;
  }
  const last = view?.last_run;
  if (last == null) return "Not run yet";
  return `Last run ${perfTime(new Date(last.finished_at), now)} · ${perfDuration(last.duration_ms)}`;
}

/** Each day of a series as a share of its largest day. */
export function dayShares(values: number[]): number[] {
  const peak = Math.max(0, ...values);
  return values.map((value) => (peak > 0 ? Math.min(Math.max(value / peak, 0), 1) : 0));
}

// MARK: Notifications and Features

const INTRO = "What makes Nest different, by area. The README has every detail.";

/** The Features page's first line, with how many show "New". */
export function featuresIntro(newCount: number): string {
  return newCount > 0 ? `${INTRO} ${String(newCount)} new since your last update.` : INTRO;
}

// The Mac's modifier symbols in the daemon's feature texts, in the order Linux names them.
const MODIFIERS: [string, string][] = [
  ["⌃", "Ctrl"],
  ["⌘", "Ctrl"],
  ["⌥", "Alt"],
  ["⇧", "Shift"],
];

/** A feature's keys as Linux names them: "⌘K" is "Ctrl+K", "⌥⌘1" is "Ctrl+Alt+1". */
export function linuxKeys(text: string): string {
  return text.replace(/[⌃⌘⌥⇧]+/gu, (run) => {
    const names = MODIFIERS.filter(([symbol]) => run.includes(symbol)).map(([, name]) => name);
    return `${[...new Set(names)].join("+")}+`;
  });
}

/** The line under the groups. */
export function featuresFooter(total: number): string {
  const count = total === 1 ? "1 feature" : `${String(total)} features`;
  return `${count}. New ones show "New" until you close Settings.`;
}
