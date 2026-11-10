// The tab strip's usage chip, ported from NestKit's UsageChip.swift and UsageMeter.lines:
// each account's windows as "30% 2h 5m" (used, then the time to its reset), a bar for its
// first window, and a tooltip naming each window and its reset.
import type { AccountWindow, EngineAccount } from "../../../api/types.ts";
import {
  engineTitle,
  meterEntries,
  ownWindows,
  type UsageMeterChoice,
} from "../../../store/usageMeter.ts";

export interface ChipWindow {
  // "30% 2h 5m", or "30% 5h" when the reset time is not reported.
  text: string;
  // "5 hour: 30%, resets in 2h 5m".
  tooltip: string;
}

export interface UsageChip {
  windows: ChipWindow[];
  // The first window's used fraction, 0 to 1.
  used: number;
  // Neutral under 80 percent, amber from 80, red from 90.
  tone: "neutral" | "amber" | "red";
}

export interface MeterLine {
  id: string;
  provider: string;
  // "Claude · Personal", for the tooltip.
  name: string;
  // The account's title on the chip, only when both lines are of one engine.
  title: string | null;
  // Null before the engine reported any window: the chip shows dots.
  chip: UsageChip | null;
}

const DAY = 24 * 60;
const WEEK = 7 * DAY;

/** "45m", "2h 5m", "2h", "3d 4h", "3d", floored to whole units; "now" once due. */
export function duration(ms: number): string {
  if (ms <= 0) return "now";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${String(minutes)}m`;
  const hours = Math.floor(minutes / 60);
  if (hours >= 24) {
    const rest = hours % 24;
    const days = String(Math.floor(hours / 24));
    return rest > 0 ? `${days}d ${String(rest)}h` : `${days}d`;
  }
  return minutes % 60 > 0 ? `${String(hours)}h ${String(minutes % 60)}m` : `${String(hours)}h`;
}

/** "5h", "wk", "30d", "90m" from a window's length; empty without one. */
function size(minutes: number | null): string {
  if (minutes === null) return "";
  if (minutes === WEEK) return "wk";
  if (minutes % DAY === 0) return `${String(minutes / DAY)}d`;
  if (minutes % 60 === 0) return `${String(minutes / 60)}h`;
  return `${String(minutes)}m`;
}

const clamped = (used: number) => Math.min(Math.max(used, 0), 1);

/** A window past its reset reads 0 until the next report, with no reset time. */
function shown(window: AccountWindow): { used: number; resetsAt: string | null } {
  return window.reset
    ? { used: 0, resetsAt: null }
    : { used: clamped(window.utilization), resetsAt: window.resets_at };
}

export function usageChip(limits: AccountWindow[], now: Date): UsageChip | null {
  const [first] = limits;
  if (first === undefined) return null;
  const windows = limits.map((window) => {
    const { used, resetsAt } = shown(window);
    const percent = `${String(Math.round(used * 100))}%`;
    if (resetsAt === null) {
      const length = size(window.minutes);
      return {
        text: length === "" ? percent : `${percent} ${length}`,
        tooltip: `${window.label}: ${percent}`,
      };
    }
    const left = duration(new Date(resetsAt).getTime() - now.getTime());
    const countdown = left === "now" ? "resets now" : `resets in ${left}`;
    return { text: `${percent} ${left}`, tooltip: `${window.label}: ${percent}, ${countdown}` };
  });
  const used = shown(first).used;
  return { windows, used, tone: used >= 0.9 ? "red" : used >= 0.8 ? "amber" : "neutral" };
}

/**
 * The chip's lines: the top two accounts the top bar shows that are not signed out and
 * whose engine can run here (not one that is not installed); with none, Claude's line
 * without numbers.
 */
export function meterLines(
  accounts: EngineAccount[],
  choice: UsageMeterChoice,
  now: Date,
  cannotRun: ReadonlySet<string> = new Set(),
): MeterLine[] {
  const byId = new Map(accounts.map((a) => [a.id, a]));
  const top = meterEntries(accounts, choice)
    .flatMap((entry) => {
      const account = byId.get(entry.id);
      return entry.shown &&
        account !== undefined &&
        account.signed_in !== false &&
        !cannotRun.has(account.provider)
        ? [account]
        : [];
    })
    .slice(0, 2);
  if (top.length === 0) {
    return [{ id: "claude", provider: "claude", name: "Claude", title: null, chip: null }];
  }
  const oneEngine = top.length > 1 && new Set(top.map((a) => a.provider)).size === 1;
  return top.map((account) => ({
    id: account.id,
    provider: account.provider,
    name: `${engineTitle(account.provider)} · ${account.title}`,
    title: oneEngine ? account.title : null,
    chip: usageChip(ownWindows(account.limits), now),
  }));
}

/** "Claude · Personal: 5 hour: 30%, resets in 2h. Codex · Codex: not reported yet". */
export function meterTooltip(lines: MeterLine[]): string {
  return lines
    .map((line) => {
      const windows = line.chip?.windows.map((w) => w.tooltip).join(". ");
      return `${line.name}: ${windows ?? "not reported yet"}`;
    })
    .join(". ");
}
