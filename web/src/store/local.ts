import { isLocalModel, LOCAL_MODEL_PREFIX, localModelValue } from "../api/payloads.ts";
import type {
  LocalApp,
  LocalModel,
  LocalModelList,
  LocalModelNotLoaded,
  LocalServerDown,
  LocalUsage,
  ModelOption,
} from "../api/types.ts";

// Local models on the phone (B106, B116 item 8), in the Mac's words (NestKit LocalModelText).

/** Why a local chat's last message or turn did not run. */
export type LocalFailure = LocalServerDown | LocalModelNotLoaded;

export interface LocalState {
  // Null until read.
  list: LocalModelList | null;
  usage: LocalUsage | null;
  // Chats whose server did not answer, or whose model did not load, by session id.
  failures: Record<string, LocalFailure>;
  // Apps whose server is being started.
  starting: LocalApp[];
  // Models whose weak-at-tools bar was dismissed on this device, by id.
  weakDismissed: string[];
}

export const NO_LOCAL: LocalState = {
  list: null,
  usage: null,
  failures: {},
  starting: [],
  weakDismissed: [],
};

export const LOCAL_TITLE = "Local";
export const LOCAL_DETAIL = "On this Mac, free, no limits";

/** The section of an engine's own local models. */
export function localDetail(engine: string): string {
  return `Run by ${engine}`;
}
export const NO_IMAGES = "This model can't read images";
export const NO_WEB_SEARCH = "Not available on local models";

const APP_TITLES: Record<LocalApp, string> = { lmstudio: "LM Studio", ollama: "Ollama" };

/** "Start Ollama". */
export function startLabel(app: LocalApp): string {
  return `Start ${APP_TITLES[app]}`;
}

/** "64k" from 65 536 tokens, "1M" from a million and more; null when unknown. */
export function contextLabel(tokens: number | null): string | null {
  if (tokens === null) return null;
  if (tokens >= 1_048_576) return `${String(Math.floor(tokens / 1_048_576))}M`;
  return tokens >= 1024 ? `${String(Math.floor(tokens / 1024))}k` : String(tokens);
}

export function isWeak(model: LocalModel): boolean {
  return model.tools === "weak" || model.tools === "none";
}

/** The model sheet's line under a local model. */
export function menuDetail(model: LocalModel): string {
  if (!model.running) {
    return model.app === null ? "Its server is not running" : `${model.app} is not running`;
  }
  if (model.tools === "weak") return "Weak at tools: edits may fail";
  if (model.tools === "none") return "Can't use tools: no edits or commands";
  const context = contextLabel(model.context);
  const parts = [model.app, context === null ? null : `${context} context`].filter(
    (part): part is string => part !== null,
  );
  return parts.length === 0 ? model.address : parts.join(" · ");
}

/** The local models as the menus list them; thinking where the model has it. */
export function localOptions(list: LocalModelList | null): ModelOption[] {
  return (list?.models ?? []).map((model) => ({
    value: localModelValue(model.id),
    display_name: model.name,
    description: menuDetail(model),
    effort_levels: model.thinking ? ["low", "medium", "high"] : [],
    supports_effort: model.thinking,
    supports_auto_mode: false,
    claude_code_effort: null,
  }));
}

/** The local model a chat's model value names, if it is one Nest has. */
export function localModelOf(local: LocalState, value: string | null): LocalModel | null {
  if (!isLocalModel(value) || value === null) return null;
  const id = value.slice(LOCAL_MODEL_PREFIX.length);
  return local.list?.models.find((m) => m.id === id) ?? null;
}

/** The chat's model when it is weak at tools and its bar was not dismissed here. */
export function weakWarning(local: LocalState, value: string | null): LocalModel | null {
  const model = localModelOf(local, value);
  if (model === null || !isWeak(model) || local.weakDismissed.includes(model.id)) return null;
  return model;
}

/** The bar above a local chat's composer while its model is weak at tools. */
export function weakBarText(model: LocalModel): string {
  return model.tools === "none"
    ? `${model.name} can't use tools: file edits and commands will fail. Choose a model that can.`
    : `${model.name} is likely too weak at tool use: file edits and commands may fail. A model of about 20B or larger works better.`;
}

/** "LM Studio is not running at localhost:1234". */
export function downTitle(down: LocalServerDown): string {
  const what = down.app === null ? "The model's server is" : `${down.app} is`;
  return down.address === null ? `${what} not running` : `${what} not running at ${down.address}`;
}

export function downBody(down: LocalServerDown): string {
  const start =
    down.app === null ? "Start the app that serves your model" : `Start ${down.app}'s server`;
  return `${start}, then Retry. Your message is kept and nothing was lost.`;
}

/** "Could not load qwen3-4b in LM Studio". */
export function notLoadedTitle(failure: LocalModelNotLoaded): string {
  const model = failure.model ?? "the model";
  return failure.app === null
    ? `Could not load ${model}`
    : `Could not load ${model} in ${failure.app}`;
}
