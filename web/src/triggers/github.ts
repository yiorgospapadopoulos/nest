// GitHub event triggers (B148): the words every client shows, and the editors' form as
// values, as NestKit's TriggerPresentation. A habit's editor edits its first GitHub
// trigger and keeps any others a pixie made as they are.
import type {
  ChatTrigger,
  ChatTriggerBody,
  EventFilter,
  GitHubEventKind,
  GitHubWatch,
  TriggerActivity,
  TriggerAuthors,
} from "../api/types.ts";

// In the order the editors list them; `phrase` follows "On GitHub when".
export const GITHUB_EVENTS: { value: GitHubEventKind; label: string; phrase: string }[] = [
  { value: "issue_opened", label: "An issue is opened", phrase: "an issue is opened" },
  { value: "pr_opened", label: "A pull request is opened", phrase: "a pull request is opened" },
  { value: "comment", label: "Someone comments", phrase: "someone comments" },
  { value: "review", label: "A review is posted", phrase: "a review is posted" },
  { value: "ci_failed", label: "CI fails", phrase: "CI fails" },
  { value: "ci_passed", label: "CI passes", phrase: "CI passes" },
];

export const AUTHORS: { value: TriggerAuthors; label: string }[] = [
  { value: "members", label: "People with write access" },
  { value: "humans", label: "Anyone but bots" },
  { value: "everyone", label: "Everyone" },
];

export const GITHUB_NOTE = "Checked on GitHub every minute. Each event starts at most one run.";
export const TRIGGER_NOTE =
  "Each event starts a chat in its own worktree. It works once, then waits for you, and cannot push.";
export const EMPTY_TRIGGERS =
  "No triggers yet. A trigger starts a chat here when something happens on GitHub.";
export const NO_REMOTE = "Add the project's GitHub address in General to use triggers.";
export const PROMPT_MAX = 4000;
export const NAME_MAX = 120;

export const authorsLabel = (authors: TriggerAuthors) =>
  AUTHORS.find((a) => a.value === authors)?.label ?? "";

const ordered = (events: GitHubEventKind[]) =>
  GITHUB_EVENTS.map((e) => e.value).filter((e) => events.includes(e));

/** "On GitHub when an issue is opened or CI fails"; null without events. */
export function githubText(watches: EventFilter[]): string | null {
  const events = ordered(watches.flatMap((w) => w.events));
  const phrases = GITHUB_EVENTS.filter((e) => events.includes(e.value)).map((e) => e.phrase);
  const last = phrases.pop();
  if (last === undefined) return null;
  return `On GitHub when ${phrases.length > 0 ? `${phrases.join(", ")} or ` : ""}${last}`;
}

/** "When CI fails · on main · labelled bug · others only", for a trigger's row. */
export function triggerSummary(filter: EventFilter): string {
  const when = githubText([filter])?.replace("On GitHub when", "When") ?? "";
  return [
    when,
    filter.branches.length > 0 ? `on ${filter.branches.join(", ")}` : null,
    filter.labels.length > 0 ? `labelled ${filter.labels.join(", ")}` : null,
    filter.authors === "members" ? null : authorsLabel(filter.authors).toLowerCase(),
  ]
    .filter((part) => part !== null && part !== "")
    .join(" · ");
}

/** "Started a chat 14:02", "Skipped 09:12 (usage)"; null when it never did anything. */
export function activityText(
  activity: TriggerActivity | undefined,
  time: (iso: string) => string,
): string | null {
  if (activity === undefined) return null;
  const words = {
    started: "Started a chat",
    queued: "Starting a chat",
    skipped: "Skipped",
    failed: "Could not start a chat",
  }[activity.outcome];
  const why = activity.reason === null ? "" : ` (${activity.reason})`;
  return `${words} ${time(activity.at)}${why}`;
}

/** Comma separated words, each once, as typed into a Labels or Branches field. */
export function parseList(text: string): string[] {
  return [
    ...new Set(
      text
        .split(",")
        .map((part) => part.trim())
        .filter((part) => part !== ""),
    ),
  ];
}

export const listText = (items: string[]) => items.join(", ");

// The GitHub part of a habit's editor.

export interface GitHubDraft {
  events: GitHubEventKind[];
  // Empty is every project on GitHub.
  projects: string[];
  labels: string;
  branches: string;
  authors: TriggerAuthors;
}

export function githubDraftOf(watches: GitHubWatch[] | undefined): GitHubDraft {
  const first = watches?.[0];
  return {
    events: first === undefined ? [] : [...first.events],
    projects: first === undefined ? [] : [...first.projects],
    labels: first === undefined ? "" : listText(first.labels),
    branches: first === undefined ? "" : listText(first.branches),
    authors: first?.authors ?? "members",
  };
}

/** The habit's GitHub triggers after the edit: the first as drafted (gone without events), then the rest. */
export function watchesOf(draft: GitHubDraft, before: GitHubWatch[] | undefined): GitHubWatch[] {
  const rest = before?.slice(1) ?? [];
  if (draft.events.length === 0) return rest;
  return [
    {
      events: ordered(draft.events),
      projects: draft.projects,
      labels: parseList(draft.labels),
      branches: parseList(draft.branches),
      authors: draft.authors,
    },
    ...rest,
  ];
}

export function toggled<T>(items: T[], item: T): T[] {
  return items.includes(item) ? items.filter((i) => i !== item) : [...items, item];
}

/** "All projects", "web", or "web and 2 more". */
export function projectsText(projects: string[]): string {
  const [first, ...rest] = projects;
  if (first === undefined) return "All projects";
  return rest.length === 0 ? first : `${first} and ${String(rest.length)} more`;
}

// A project's trigger editor.

export interface TriggerDraft {
  name: string;
  prompt: string;
  events: GitHubEventKind[];
  labels: string;
  branches: string;
  authors: TriggerAuthors;
  enabled: boolean;
}

export function newTriggerDraft(): TriggerDraft {
  return {
    name: "",
    prompt: "",
    events: [],
    labels: "",
    branches: "",
    authors: "members",
    enabled: true,
  };
}

export function triggerDraftOf(trigger: ChatTrigger): TriggerDraft {
  return {
    name: trigger.name,
    prompt: trigger.prompt,
    events: [...trigger.events],
    labels: listText(trigger.labels),
    branches: listText(trigger.branches),
    authors: trigger.authors,
    enabled: trigger.enabled,
  };
}

/** Why it cannot be saved yet; an empty name only keeps Save off. */
export function triggerProblem(draft: TriggerDraft): string | null {
  if (draft.name.trim().length > NAME_MAX)
    return `A name has at most ${String(NAME_MAX)} characters`;
  if (draft.events.length === 0) return "Choose at least one event";
  if (draft.prompt.trim() === "") return "Say what the chat should do";
  if (draft.prompt.trim().length > PROMPT_MAX) {
    return `The instructions have at most ${String(PROMPT_MAX)} characters`;
  }
  return null;
}

export const canSaveTrigger = (draft: TriggerDraft) =>
  draft.name.trim() !== "" && triggerProblem(draft) === null;

export function triggerBody(draft: TriggerDraft): ChatTriggerBody {
  return {
    name: draft.name.trim(),
    prompt: draft.prompt.trim(),
    enabled: draft.enabled,
    events: ordered(draft.events),
    labels: parseList(draft.labels),
    branches: parseList(draft.branches),
    authors: draft.authors,
  };
}
