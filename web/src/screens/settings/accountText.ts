import type {
  AccountWindow,
  BankedCredit,
  CheckResult,
  DownloadedModel,
  EngineAccount,
  FoundModel,
  LocalModel,
} from "../../api/types.ts";
import { percent } from "../../format.ts";
import { contextLabel } from "../../store/local.ts";
import type { StatusTone } from "./rows.tsx";

// Settings > Accounts' and Usage's words for engine accounts (B98) and local models (B106),
// as the Mac's AccountText, UsageText and LocalModelText write them.

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY_MS = 24 * 3600_000;

const two = (n: number) => String(n).padStart(2, "0");

/** "18:30" today, "Mon 09:00" within six days, else "14 Oct". */
export function resetTime(at: Date, now: Date): string {
  const time = `${two(at.getHours())}:${two(at.getMinutes())}`;
  if (at.toDateString() === now.toDateString()) return time;
  const ahead = at.getTime() - now.getTime();
  if (ahead > 0 && ahead < 6 * DAY_MS) return `${String(WEEKDAYS[at.getDay()])} ${time}`;
  return `${String(at.getDate())} ${String(MONTHS[at.getMonth()])}`;
}

/** The percent used; a window past its reset reads 0 until the next report. */
export function used(window: AccountWindow): number {
  return window.reset ? 0 : percent(window.utilization);
}

/** "5 hour 64% · 23:40"; a window past its reset, or without a reset time, has no time. */
export function limitLine(window: AccountWindow, now: Date): string {
  const line = `${window.label} ${String(used(window))}%`;
  if (window.reset || window.resets_at === null) return line;
  return `${line} · ${resetTime(new Date(window.resets_at), now)}`;
}

/** "Resets 18:30", "Reset" past its reset time, or "Reset time not reported". */
export function resetLine(window: AccountWindow, now: Date): string {
  if (window.reset) return "Reset";
  if (window.resets_at === null) return "Reset time not reported";
  return `Resets ${resetTime(new Date(window.resets_at), now)}`;
}

/** The row's line under the title: the plan, then the email unless it is the title. */
export function accountDetail(account: EngineAccount): string | null {
  const email = account.email === "" || account.email === account.title ? null : account.email;
  const parts = [account.plan, email].filter((part): part is string => part !== null);
  return parts.length === 0 ? null : parts.join(" · ");
}

/** The login in a word; signing in is optional while local models run chats (B106). */
export function accountState(
  account: EngineAccount,
  optional: boolean,
): { tone: StatusTone; label: string } {
  if (account.signing_in) return { tone: "run", label: "Finish in the browser" };
  if (account.signed_in === true) return { tone: "ok", label: "Signed in" };
  if (account.signed_in === false) {
    return { tone: "wait", label: optional ? "Not signed in, optional" : "Signed out" };
  }
  return { tone: "idle", label: "Not checked" };
}

/** What the Mac says before signing out of an engine's first account. */
export function signOutNote(account: EngineAccount, optional: boolean): string {
  if (!account.first || optional) return "";
  return account.provider === "claude"
    ? "Claude Code on this Mac signs out too. Chats cannot run until you sign in again."
    : "Codex on this Mac signs out too. Codex chats cannot run until you sign in again.";
}

/** "Banked resets", with the count available when there are any. */
export function bankedTitle(available: number): string {
  return available > 0 ? `Banked resets ${String(available)}` : "Banked resets";
}

export function creditTitle(credit: BankedCredit): string {
  return credit.title === null || credit.title === "" ? "Reset" : credit.title;
}

/** "expires 9 Nov"; null when Codex gives no date. */
export function creditExpiry(credit: BankedCredit): string | null {
  if (credit.expires_at === null) return null;
  const at = new Date(credit.expires_at);
  return `expires ${String(at.getDate())} ${String(MONTHS[at.getMonth()])}`;
}

// Local models.

/** "LM Studio · localhost:1234 · 64k context", leaving out what is unknown. */
export function localPlace(model: LocalModel | FoundModel): string {
  const context = contextLabel(model.context);
  return [model.app, model.address, context === null ? null : `${context} context`]
    .filter((part): part is string => part !== null)
    .join(" · ");
}

/** A row's state in Settings > Accounts; not running first, since nothing else matters then. */
export function localState(model: LocalModel): { tone: StatusTone; label: string } {
  if (!model.running) return { tone: "wait", label: "Server not running" };
  if (model.tools === "weak") return { tone: "wait", label: "Weak at tools" };
  if (model.tools === "none") return { tone: "bad", label: "Can't use tools" };
  return { tone: "ok", label: "Ready" };
}

/** The quiet tag at a found model's end: added, or good at tools. */
export function foundTag(model: FoundModel): string | null {
  if (model.added) return "Added";
  return model.tools === "good" ? "Good at tools" : null;
}

/** The warnings under a found model that may fail as an agent or fill the Mac's memory. */
export function foundWarnings(model: FoundModel): string[] {
  const tools =
    model.tools === "weak"
      ? (model.weak_reason ?? "Likely too weak at tools: edits and commands may fail")
      : model.tools === "none"
        ? (model.weak_reason ?? "Can't use tools, so an agent can't edit files or run commands")
        : null;
  return [tools, model.memory_warning].filter((w): w is string => w !== null);
}

/** "Ollama models folder · start Ollama to use it". */
export function downloadedLine(model: DownloadedModel): string {
  return `${model.source} · ${model.hint}`;
}

/** The sheet's add button. */
export function addTitle(count: number): string {
  if (count === 0) return "Add models";
  return count === 1 ? "Add 1 model" : `Add ${String(count)} models`;
}

/** The line under Check: whether the server at the address can run agents. */
export function checkedLine(check: CheckResult, address: string): { text: string; ok: boolean } {
  const server = check.server;
  if (check.ok && server !== null) {
    const count = check.models.length === 1 ? "1 model" : `${String(check.models.length)} models`;
    const engines = [
      server.messages || server.chat ? "Claude Code" : null,
      server.responses || server.chat ? "Codex" : null,
    ].filter((e): e is string => e !== null);
    return {
      text: `Found ${server.app ?? "a server"} at ${address} with ${count}. It works with ${engines.join(" and ")}.`,
      ok: true,
    };
  }
  const text =
    check.error === "unreachable"
      ? `Nothing answered at ${address}. Start the app that serves your model, then Check again.`
      : check.error === "no_tools"
        ? `The server at ${address} answered, but it can't run tools, so an agent can't edit files or run commands on it.`
        : check.error === "no_models"
          ? `The server at ${address} answered, but it has no models loaded. Load one, then Check again.`
          : `The server at ${address} can't run agents.`;
  return { text, ok: false };
}

/** "Claude Code" or "Codex", as the engine local chats run on. */
export function localEngineName(engine: string): string {
  return engine === "claude" ? "Claude Code" : "Codex";
}

/** The quiet note under the local models. */
export function localNote(engine: string): string {
  const other = engine === "claude" ? "codex" : "claude";
  return `Chats on a local model run on ${localEngineName(engine)}; to use ${localEngineName(other)}, change Local chats run on in a model menu. No limits apply, so Usage shows token counts only.`;
}
