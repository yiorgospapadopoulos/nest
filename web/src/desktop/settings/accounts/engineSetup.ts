import type { ProviderInfo } from "../../../api/types.ts";

// One row of More engines in Settings > Accounts (B107), as NestKit's EngineSetup: an
// engine past Claude and Codex, its state in a word and its one action.

export type EngineAction =
  | { kind: "none" }
  // Nest fetches the engine; `again` after a failed install.
  | { kind: "install"; again: boolean }
  // The engine's login command, run in a terminal.
  | { kind: "signIn"; command: string }
  // A key field the button reveals.
  | { kind: "addKey"; placeholder: string }
  | { kind: "removeKey" };

export const NOT_ON_PATH = "Not on PATH: install it yourself";
export const GIT_WARNING =
  "Nest cannot block this engine's git commands, so it may commit or push on its own.";

export interface EngineSetup {
  name: string;
  title: string;
  version: string | null;
  state: string;
  ready: boolean;
  installing: boolean;
  // Why installing failed, in plain words.
  failure: string | null;
  action: EngineAction;
  gitWarning: string | null;
}

const NONE: EngineAction = { kind: "none" };

function signIn(provider: ProviderInfo): [string, EngineAction] {
  const signedIn = provider.signed_in;
  if (provider.sign_in === "api_key") {
    if (signedIn === true) return ["Ready", { kind: "removeKey" }];
    return [
      "No key",
      { kind: "addKey", placeholder: `Paste your ${provider.display_name} API key` },
    ];
  }
  if (provider.sign_in === "browser") return [signedIn === false ? "Signed out" : "Ready", NONE];
  const state = signedIn === true ? "Ready" : signedIn === false ? "Signed out" : "Not checked";
  if (signedIn !== true && provider.login_command !== null) {
    return [state, { kind: "signIn", command: provider.login_command }];
  }
  return [state, NONE];
}

export function engineSetup(provider: ProviderInfo): EngineSetup {
  const [state, action]: [string, EngineAction] =
    provider.state === "ready"
      ? signIn(provider)
      : provider.state === "installing"
        ? ["Installing", NONE]
        : provider.state === "not_installed"
          ? provider.installable
            ? ["Not installed", { kind: "install", again: false }]
            : [NOT_ON_PATH, NONE]
          : ["Install failed", provider.installable ? { kind: "install", again: true } : NONE];
  return {
    name: provider.name,
    title: provider.display_name,
    version: provider.version,
    state,
    ready: state === "Ready",
    installing: provider.state === "installing",
    failure: provider.state === "install_failed" ? provider.state_detail : null,
    action,
    gitWarning: provider.git_guard ? null : GIT_WARNING,
  };
}

/** Every engine but Claude and Codex, whose sections stay their own, in the daemon's order. */
export function otherEngines(providers: readonly ProviderInfo[]): EngineSetup[] {
  return providers.filter((p) => p.name !== "claude" && p.name !== "codex").map(engineSetup);
}
