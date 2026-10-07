import type {
  AccountInfo,
  AgentDefaults,
  Approval,
  ClaudeChat,
  CommandList,
  Connector,
  Effort,
  HarnessEvent,
  ModelList,
  ModelOption,
  MonthUsage,
  NotificationSettings,
  PrCheck,
  PrStatus,
  QueuedMessage,
  RepoConfig,
  Session,
  SessionDetail,
  SessionDiff,
  UsageLimits,
} from "../api/types.ts";

import { NO_BACKGROUND } from "../store/state.ts";

export { NO_BACKGROUND };

export const NOW = "2026-10-06T10:00:00Z";

export function repo(name: string): RepoConfig {
  return {
    name,
    path: `/Users/me/${name}`,
    git: true,
    default_branch: "main",
    worktree: { default: true, link: [], setup: [], setup_timeout_seconds: 900 },
  };
}

export function session(overrides: Partial<Session> = {}): Session {
  return {
    id: "s1",
    repo: "todo-ui",
    title: "Validate contact form",
    prompt: "Validate the contact form",
    mode: "worktree",
    cwd: "/w/s1",
    model: null,
    effort: null,
    permission_mode: "default",
    provider: "claude",
    base_ref: "abc",
    state: "idle",
    worktree_path: "/w/s1",
    branch: "agent/contact",
    provider_session_id: null,
    git_violation: false,
    created_at: NOW,
    updated_at: NOW,
    last_error: null,
    commit_sha: null,
    pr_url: null,
    allowed_tools: [],
    pinned: false,
    archived_at: null,
    context: null,
    pr: null,
    pr_summary: null,
    stuck: null,
    ...overrides,
  };
}

export function claudeChat(overrides: Partial<ClaudeChat> = {}): ClaudeChat {
  return {
    id: "c1",
    repo: "todo-ui",
    title: "Tune the hero section",
    cwd: "/Users/me/todo-ui",
    worktree: null,
    created_at: NOW,
    last_activity_at: NOW,
    message_count: 4,
    open_in_claude_code: false,
    entrypoint: "claude-desktop",
    automated: false,
    archived: false,
    ...overrides,
  };
}

export function detail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return {
    ...session(),
    tasks: [],
    agents: [],
    background: NO_BACKGROUND,
    queued: [],
    ...overrides,
  };
}

export function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "q1",
    session_id: "s1",
    repo: "todo-ui",
    title: "Validate contact form",
    kind: "permission",
    status: "pending",
    payload: {
      tool: "Bash",
      input: { command: "npm install zod", description: "Adds zod" },
      title: null,
    },
    resolution: null,
    created_at: NOW,
    resolved_at: null,
    ...overrides,
  };
}

export function question(overrides: Partial<Approval> = {}): Approval {
  return approval({
    id: "q2",
    kind: "question",
    payload: {
      tool_use_id: "t9",
      questions: [
        {
          question: "DAG or tree?",
          header: "Structure",
          multi_select: false,
          options: [
            { label: "Tree", description: "Simple", recommended: false },
            { label: "DAG", description: "Shares lines", recommended: true },
          ],
        },
      ],
    },
    ...overrides,
  });
}

export function review(overrides: Partial<Approval> = {}): Approval {
  return approval({
    id: "q3",
    kind: "review",
    payload: {
      base: "abc",
      files: 3,
      additions: 48,
      deletions: 19,
      paths: ["a.css", "b.tsx", "c.tsx"],
      summary: "Raised contrast",
    },
    ...overrides,
  });
}

export function plan(overrides: Partial<Approval> = {}): Approval {
  return approval({
    id: "q4",
    kind: "plan",
    payload: { plan: "## Plan\n\n1. Add **zod**\n2. Validate the form", tool_use_id: "t7" },
    ...overrides,
  });
}

export function check(name: string, state: PrCheck["state"] = "success"): PrCheck {
  return { name, state, url: `https://ci.example/${name}` };
}

/** An open pull request; `checks` sets the items and the summary follows them. */
export function prStatus(
  overrides: Partial<Omit<PrStatus, "checks">> & { checks?: PrCheck[] } = {},
): PrStatus {
  const { checks = [check("unit"), check("lint")], ...rest } = overrides;
  const count = (state: PrCheck["state"]) => checks.filter((c) => c.state === state).length;
  const failed = count("failure");
  const pending = count("pending");
  return {
    number: 7,
    url: "https://github.com/me/todo-ui/pull/7",
    title: "Validate contact form",
    state: "open",
    checks: {
      state:
        failed > 0 ? "failure" : pending > 0 ? "pending" : checks.length > 0 ? "success" : "none",
      passed: count("success") + count("skipped"),
      failed,
      pending,
      items: checks,
    },
    mergeable: true,
    merge_state: "clean",
    review_decision: null,
    head_sha: "abc123",
    created_at: NOW,
    changed_at: NOW,
    updated_at: NOW,
    ...rest,
  };
}

export function mergeApproval(overrides: Partial<Approval> = {}): Approval {
  return approval({
    id: "q5",
    kind: "merge",
    payload: {
      number: 7,
      title: "Validate contact form",
      url: "https://github.com/me/todo-ui/pull/7",
      head_sha: "abc123",
      checks: { state: "success", passed: 2, failed: 0, pending: 0 },
    },
    ...overrides,
  });
}

export function queuedMessage(overrides: Partial<QueuedMessage> = {}): QueuedMessage {
  return { id: "m1", text: "Then add tests", attachments: [], created_at: NOW, ...overrides };
}

export function commandList(overrides: Partial<CommandList> = {}): CommandList {
  return {
    source: "session",
    commands: [
      { name: "clear", description: "Clear the conversation", argument_hint: null },
      { name: "compact", description: "Summarise the conversation", argument_hint: "[focus]" },
      { name: "review", description: "Review a pull request", argument_hint: null },
      { name: "security-review", description: null, argument_hint: null },
    ],
    agents: [{ name: "Explore", description: "Searches the code" }],
    updated_at: NOW,
    ...overrides,
  };
}

export function event(overrides: Partial<HarnessEvent> & { type: string }): HarnessEvent {
  return { id: 1, ts: NOW, session_id: "s1", payload: {}, ...overrides };
}

export function diff(): SessionDiff {
  return {
    base: "abc",
    stats: { files: 2, additions: 2, deletions: 1 },
    files: [
      {
        path: "app/globals.css",
        old_path: null,
        status: "modified",
        additions: 2,
        deletions: 1,
        binary: false,
        truncated: false,
        hunks: [
          {
            old_start: 12,
            old_lines: 2,
            new_start: 12,
            new_lines: 3,
            header: ":root",
            lines: [
              { kind: "context", text: "  --bg: #000;", old_line: 12, new_line: 12 },
              { kind: "delete", text: "  --muted: #666;", old_line: 13, new_line: null },
              { kind: "add", text: "  --muted: #aaa;", old_line: null, new_line: 13 },
              { kind: "add", text: "  color-scheme: dark;", old_line: null, new_line: 14 },
            ],
          },
        ],
      },
      {
        path: "logo.png",
        old_path: null,
        status: "added",
        additions: 0,
        deletions: 0,
        binary: true,
        truncated: false,
        hunks: [],
      },
    ],
  };
}

export function connector(overrides: Partial<Connector> = {}): Connector {
  return {
    name: "claude.ai Gmail",
    display_name: "Gmail",
    group: "claude.ai",
    status: "connected",
    error: null,
    manage_hint: "claude.ai",
    source: "s1",
    last_seen_at: NOW,
    ...overrides,
  };
}

export function month(year: number, monthNumber: number): MonthUsage {
  const days = new Date(year, monthNumber, 0).getDate();
  return {
    year,
    month: monthNumber,
    sessions: 4,
    tokens: {
      input_tokens: 1,
      output_tokens: 1,
      cache_creation_input_tokens: 1,
      cache_read_input_tokens: 1,
      total: 2_400_000,
    },
    days: Array.from({ length: days }, (_, i) => ({
      date: `${String(year)}-${String(monthNumber).padStart(2, "0")}-${String(i + 1).padStart(2, "0")}`,
      tokens: i === 0 ? 1_200_000 : i === 1 ? 300 : 0,
      sessions: i === 0 ? 3 : i === 1 ? 1 : 0,
    })),
  };
}

export function limits(): UsageLimits {
  return {
    five_hour: { utilization: 0.3, resets_at: null, updated_at: NOW },
    seven_day: null,
  };
}

export function notificationSettings(
  overrides: Partial<NotificationSettings> = {},
): NotificationSettings {
  return {
    kinds: {
      needs_approval: true,
      question: true,
      review_ready: true,
      failed: true,
      finished: false,
      ci_failed: false,
      ready_to_merge: false,
      stuck: false,
    },
    quiet_hours: null,
    ntfy: { enabled: false, server: "https://ntfy.sh", topic: null, click_base_url: null },
    vapid_subject: "mailto:harness@example.com",
    ...overrides,
  };
}

const LEVELS: Effort[] = ["low", "medium", "high", "xhigh", "max"];

/** Claude Code's list, as the daemon serves it: Haiku takes no thinking level. */
export function models(): ModelOption[] {
  return [
    {
      value: "default",
      display_name: "Default (recommended)",
      description: "Opus 5.5 · Best for everyday, complex tasks",
      effort_levels: LEVELS,
      supports_effort: true,
    },
    {
      value: "opus",
      display_name: "Opus 5.5",
      description: "Most capable for complex work",
      effort_levels: LEVELS,
      supports_effort: true,
    },
    {
      value: "haiku",
      display_name: "Haiku 4.5",
      description: "Fastest for quick answers",
      effort_levels: [],
      supports_effort: false,
    },
    {
      value: "claude-opus-4-6",
      display_name: "Opus 4.6",
      description: "Previous Opus",
      effort_levels: ["low", "medium", "high", "max"],
      supports_effort: true,
    },
  ];
}

export function modelList(overrides: Partial<ModelList> = {}): ModelList {
  return { models: models(), updated_at: NOW, ...overrides };
}

export function account(overrides: Partial<AccountInfo> = {}): AccountInfo {
  return {
    display_name: "Sam",
    email: "me@example.com",
    plan: "Claude Max",
    organization: null,
    ...overrides,
  };
}

export function agentDefaults(overrides: Partial<AgentDefaults> = {}): AgentDefaults {
  return { model: null, effort: null, permission_mode: "default", mode: "in_place", ...overrides };
}
