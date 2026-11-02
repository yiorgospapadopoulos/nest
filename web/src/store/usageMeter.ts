import type { AccountWindow, EngineAccount } from "../api/types.ts";

// Which accounts Settings > Usage shows and "Top bar shows" checks, on this device only (B98),
// as the Mac's UsageMeter (NestKit Presentation/UsageMeter.swift) has them.

export interface UsageMeterChoice {
  // Account ids in the user's order; accounts it does not name follow in the daemon's.
  order: string[];
  // The checked accounts; null until the user checks or unchecks one, while the account in
  // use of each engine shows.
  shown: string[] | null;
  // The engines unchecked before B98 (`nest.usageBarHidden`): their accounts start unchecked.
  hiddenEngines: string[];
}

export const NO_METER_CHOICE: UsageMeterChoice = { order: [], shown: null, hiddenEngines: [] };

/** One row of "Top bar shows". */
export interface MeterAccount {
  id: string;
  provider: string;
  // "Claude · Personal".
  name: string;
  // "Max 20x · in use", "Signed out".
  detail: string;
  shown: boolean;
}

/** One account's windows on the Usage page, under "<Engine> · <title>". */
export interface LimitGroup {
  id: string;
  provider: string;
  title: string;
  // Turns run on it: "in use".
  active: boolean;
  limits: AccountWindow[];
}

const ENGINES: Record<string, string> = {
  claude: "Claude",
  codex: "Codex",
  opencode: "OpenCode",
  gemini: "Gemini CLI",
  cursor: "Cursor agent",
};

/** "Claude", "Codex", the other known engines' names, else the name capitalized. */
export function engineTitle(provider: string): string {
  return ENGINES[provider] ?? provider.charAt(0).toUpperCase() + provider.slice(1);
}

function shows(choice: UsageMeterChoice, account: EngineAccount): boolean {
  return choice.shown === null
    ? account.active && !choice.hiddenEngines.includes(account.provider)
    : choice.shown.includes(account.id);
}

function nameOf(account: EngineAccount): string {
  return `${engineTitle(account.provider)} · ${account.title}`;
}

/** Accounts with limits to show: Claude's and Codex's, and any other that reported some. */
function metered(accounts: EngineAccount[]): EngineAccount[] {
  return accounts.filter(
    (a) => a.provider === "claude" || a.provider === "codex" || a.limits.length > 0,
  );
}

function ordered(accounts: EngineAccount[], choice: UsageMeterChoice): EngineAccount[] {
  const listed = metered(accounts);
  const named = choice.order.flatMap((id) => listed.filter((a) => a.id === id));
  return [...named, ...listed.filter((a) => !choice.order.includes(a.id))];
}

/** Every account, in the user's order, as "Top bar shows" lists them. */
export function meterEntries(accounts: EngineAccount[], choice: UsageMeterChoice): MeterAccount[] {
  return ordered(accounts, choice).map((account) => {
    const state = account.signed_in === false ? "Signed out" : account.plan;
    const detail = [state, account.active ? "in use" : null].filter((part) => part !== null);
    return {
      id: account.id,
      provider: account.provider,
      name: nameOf(account),
      detail: detail.join(" · "),
      shown: shows(choice, account),
    };
  });
}

/**
 * The checked accounts that are not signed out, in the user's order: the Usage page's
 * limits; else the first account in use, so the limits stay.
 */
export function limitGroups(accounts: EngineAccount[], choice: UsageMeterChoice): LimitGroup[] {
  const shown = ordered(accounts, choice).filter((a) => shows(choice, a) && a.signed_in !== false);
  const groups =
    shown.length > 0
      ? shown
      : metered(accounts)
          .filter((a) => a.active)
          .slice(0, 1);
  return groups.map((account) => ({
    id: account.id,
    provider: account.provider,
    title: nameOf(account),
    active: account.active,
    limits: account.limits,
  }));
}

/** One account in the Chats header's usage (B116): its shortest window. */
export interface ChipEntry {
  id: string;
  provider: string;
  // "63% 2h": used, then the time to its reset; "63% 5h" when no reset is reported.
  text: string;
  used: number;
  tone: "ok" | "warn" | "bad";
}

/**
 * "45m", "2h", "3d", floored; "now" once due. The Mac's UsageChip adds the next unit
 * ("2h 5m"); the phone's header has room for one.
 */
function duration(ms: number): string {
  if (ms <= 0) return "now";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${String(minutes)}m`;
  const hours = Math.floor(minutes / 60);
  return hours >= 24 ? `${String(Math.floor(hours / 24))}d` : `${String(hours)}h`;
}

/** The top two checked accounts that reported a window, each as its shortest one. */
export function chipEntries(
  accounts: EngineAccount[],
  choice: UsageMeterChoice,
  now: Date,
): ChipEntry[] {
  const entries = ordered(accounts, choice)
    .filter((a) => shows(choice, a) && a.signed_in !== false)
    .flatMap((account): ChipEntry[] => {
      // A window of unknown length sorts last.
      const length = (w: AccountWindow) => w.minutes ?? Number.POSITIVE_INFINITY;
      const [window] = [...account.limits].sort((a, b) => length(a) - length(b));
      if (window === undefined) return [];
      const used = Math.min(Math.max(window.utilization, 0), 1);
      const percent = `${String(Math.round(used * 100))}%`;
      const left =
        window.resets_at !== null
          ? duration(new Date(window.resets_at).getTime() - now.getTime())
          : window.minutes !== null
            ? duration(window.minutes * 60_000)
            : null;
      const text = left === null ? percent : `${percent} ${left}`;
      const tone = used >= 0.9 ? "bad" : used >= 0.8 ? "warn" : "ok";
      return [{ id: account.id, provider: account.provider, text, used, tone }];
    });
  return entries.slice(0, 2);
}

/** The choice after checking or unchecking `id`: the first check keeps the others as shown. */
export function withShown(
  choice: UsageMeterChoice,
  id: string,
  shown: boolean,
  entries: MeterAccount[],
): UsageMeterChoice {
  const checked = choice.shown ?? entries.filter((e) => e.shown).map((e) => e.id);
  const others = checked.filter((other) => other !== id);
  return { ...choice, shown: shown ? [...others, id] : others, hiddenEngines: [] };
}

/** The ids with the one at `from` placed at `to`, as a drag ends. */
export function movedTo(ids: string[], from: number, to: number): string[] {
  const next = [...ids];
  const [id] = next.splice(from, 1);
  if (id !== undefined) next.splice(Math.max(0, Math.min(to, next.length)), 0, id);
  return next;
}
