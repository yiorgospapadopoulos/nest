// The setup guide's steps and rules (B130), the same on the Linux and Mac apps. This is the
// Linux list: Dictation is the Mac's, and the Secret Service has passed if the guide shows.
import type { ModelOption, SetupCheck, SetupCheckState } from "../../api/types.ts";
import { catalogFor } from "../../store/selectors.ts";
import { localOptions } from "../../store/local.ts";
import type { State } from "../../store/state.ts";
import type { DraftModel } from "../layout/project.ts";

export type StepId =
  | "engine"
  | "git"
  | "github"
  | "service"
  | "tailscale"
  | "notifications"
  | "ntfy"
  | "secret_service"
  | "first_chat";

export interface Step {
  id: StepId;
  rail: string;
  title: string;
}

export const STEPS: readonly Step[] = [
  { id: "engine", rail: "Engine", title: "Sign in to an engine" },
  { id: "git", rail: "git", title: "git" },
  { id: "github", rail: "GitHub", title: "GitHub" },
  { id: "service", rail: "Background service", title: "Background service" },
  { id: "tailscale", rail: "Tailscale and iPhone", title: "Pair your iPhone" },
  { id: "notifications", rail: "Notifications", title: "Notifications" },
  { id: "ntfy", rail: "ntfy", title: "ntfy" },
  { id: "secret_service", rail: "Secret Service", title: "Secret Service" },
  { id: "first_chat", rail: "First chat", title: "Send your first message" },
];

export type Mark = "ok" | "todo" | "now" | "skipped";

/** The rail's mark: done first, then open now, then skipped; a check that failed is not done. */
export function markOf(
  state: SetupCheckState | undefined,
  open: boolean,
  skipped: boolean,
  answered: boolean,
): Mark {
  if (state === "ok" || answered) return "ok";
  if (open) return "now";
  return skipped ? "skipped" : "todo";
}

/**
 * Any step but the engine, the one that cannot be skipped: without it nothing in Nest runs.
 * The last step has nothing to skip to; Finish leaves it.
 */
export const canSkip = (step: StepId) => step !== "engine" && step !== "first_chat";

/** Continue moves on whatever the state, except on the engine step. */
export const canContinue = (step: StepId, engineReady: boolean) => step !== "engine" || engineReady;

/**
 * Finishing a first run needs an engine. A guide reopened from Settings can always be left:
 * someone who signed out later is not locked in it.
 */
export const canFinish = (firstRun: boolean, engineReady: boolean) => !firstRun || engineReady;

export function checksById(checks: readonly SetupCheck[]): Map<string, SetupCheck> {
  return new Map(checks.map((check) => [check.id, check]));
}

// As the daemon's providers/one_off.py, cheapest first.
const CHEAP = ["haiku", "nano", "mini", "lite", "flash", "luna", "small"];

/** The first model named like a small one; null leaves the engine's default. */
export function cheapestModel(models: readonly ModelOption[]): string | null {
  for (const word of CHEAP) {
    const found = models.find((m) => `${m.value} ${m.display_name}`.toLowerCase().includes(word));
    if (found !== undefined) return found.value;
  }
  return null;
}

/**
 * What the first chat runs on: the cheapest model of the first engine signed in, else the
 * first local model; null leaves the new chat's defaults.
 */
export function firstChatModel(state: State): DraftModel | null {
  const signedIn = state.settings.accounts?.find((account) => account.signed_in === true);
  if (signedIn !== undefined) {
    const catalog = catalogFor(state, signedIn.provider);
    const model = cheapestModel(catalog.models) ?? catalog.defaultModel;
    return model === null ? null : { provider: signedIn.provider, model };
  }
  const local = localOptions(state.local.list)[0];
  const provider = state.agentDefaults?.provider;
  return local === undefined || provider == null ? null : { provider, model: local.value };
}

export type TailscaleStage = "off" | "unshared" | "shared";

/** How far Tailscale has come, from what the check's fix asks for. */
export function tailscaleStage(check: SetupCheck | undefined): TailscaleStage {
  if (check === undefined) return "off";
  if (check.fix === null) return "shared";
  return check.fix.value.includes("serve") ? "unshared" : "off";
}
