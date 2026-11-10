import type {
  AccountWindow,
  DownloadedModel,
  EngineAccount,
  FoundModel,
  LocalModel,
} from "../api/types.ts";

// Engine accounts (B98) and local models (B106) as the daemon sends them.

const NOW = new Date().toISOString();

export function accountWindow(overrides: Partial<AccountWindow> = {}): AccountWindow {
  return {
    label: "5 hour",
    scope: null,
    minutes: 300,
    utilization: 0.3,
    resets_at: null,
    updated_at: NOW,
    reset: false,
    ...overrides,
  };
}

/** Claude's first account, signed in and in use, unless `overrides` say otherwise. */
export function engineAccount(overrides: Partial<EngineAccount> = {}): EngineAccount {
  return {
    id: "claude-main",
    provider: "claude",
    name: "Personal",
    title: "Personal",
    email: "me@example.com",
    plan: "Max 20x",
    signed_in: true,
    active: true,
    first: true,
    signing_in: false,
    error: null,
    limits: [
      accountWindow(),
      accountWindow({ label: "Weekly", minutes: 10080, utilization: 0.81 }),
    ],
    checked_at: NOW,
    banked_resets: null,
    limit_reset: false,
    ...overrides,
  };
}

/** Claude's Personal (in use) and Work, then Codex's own login. */
export function accountList(): EngineAccount[] {
  return [
    engineAccount(),
    engineAccount({
      id: "claude-work",
      name: "Work",
      title: "Work",
      email: "me@work.example",
      plan: "Pro",
      active: false,
      first: false,
      limits: [
        accountWindow({ utilization: 0 }),
        accountWindow({ label: "Weekly", minutes: 10080, utilization: 0.42 }),
      ],
    }),
    codexAccount(),
  ];
}

export function codexAccount(overrides: Partial<EngineAccount> = {}): EngineAccount {
  return engineAccount({
    id: "codex-main",
    provider: "codex",
    name: null,
    title: "me@example.com",
    plan: "ChatGPT Plus",
    limits: [accountWindow({ label: "30 day", minutes: 43200, utilization: 0.04 })],
    banked_resets: { available: 0, credits: null },
    ...overrides,
  });
}

export function localModel(overrides: Partial<LocalModel> = {}): LocalModel {
  return {
    id: "lm-qwen",
    server_id: "lmstudio",
    model: "qwen3-coder-30b",
    name: "qwen3-coder-30b",
    address: "localhost:1234",
    app: "LM Studio",
    context: 65536,
    tools: "good",
    weak_reason: null,
    vision: false,
    thinking: false,
    running: true,
    has_key: false,
    memory_warning: null,
    ...overrides,
  };
}

export function foundModel(overrides: Partial<FoundModel> = {}): FoundModel {
  return {
    address: "localhost:1234",
    app: "LM Studio",
    model: "qwen3-coder-30b",
    name: "qwen3-coder-30b",
    context: 65536,
    tools: "good",
    weak_reason: null,
    vision: false,
    thinking: false,
    added: false,
    memory_warning: null,
    ...overrides,
  };
}

export function downloadedModel(overrides: Partial<DownloadedModel> = {}): DownloadedModel {
  return {
    name: "devstral-small-2",
    source: "Ollama models folder",
    path: "/Users/me/.ollama/models/devstral-small-2",
    hint: "start Ollama to use it",
    start: "ollama",
    ...overrides,
  };
}
