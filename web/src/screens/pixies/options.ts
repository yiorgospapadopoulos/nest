import type {
  Autonomy,
  Mascot,
  PixieBackground,
  ProjectAccess,
  ReportSeverity,
} from "../../api/types.ts";
import type { Option } from "../chat/options.ts";

export const MASCOTS: readonly Mascot[] = [
  "invader",
  "ghost",
  "cat",
  "owl",
  "robot",
  "frog",
  "mushroom",
  "bunny",
  "crab",
  "sprout",
];

export const BACKGROUNDS: Record<PixieBackground, string> = {
  plain: "Plain",
  meadow: "Meadow",
  dusk: "Dusk",
  night: "Night",
  dawn: "Dawn",
};

interface Choice {
  label: string;
  hint: string;
}

export const PROJECT_ACCESS: Record<ProjectAccess, Choice> = {
  edit: { label: "Edit", hint: "Reads and edits its projects like any chat" },
  read: { label: "Read only", hint: "Reads its projects, writes only in its own folder" },
  none: { label: "None", hint: "Works only in its own folder" },
};

// What each level lets the pixie do with harness tools in its chat runs (B41).
export const AUTONOMY: Record<Autonomy, Choice> = {
  observe: { label: "Observe", hint: "Reads chats in its projects" },
  message: { label: "Message", hint: "Also writes to them, nudges or stops them" },
  start: { label: "Start", hint: "Also starts chats in their own worktree" },
  answer: {
    label: "Answer",
    hint: "Also answers approvals, questions and plans in chats it started",
  },
};

// The least severe report that reaches the phone (B42).
export const REPORT_PUSH: Record<ReportSeverity, Choice> = {
  action: { label: "Needs action", hint: "Only reports that need you" },
  warn: { label: "Warnings and up", hint: "Also warnings" },
  info: { label: "Everything", hint: "Every report" },
};

/** "1 report needs action", "3 reports need action". */
export function actionText(count: number): string {
  return count === 1 ? "1 report needs action" : `${String(count)} reports need action`;
}

/** A picker's options, in the order the choices are listed. */
export function optionsOf(choices: Record<string, Choice>): Option<string>[] {
  return Object.entries(choices).map(([value, { label, hint }]) => ({ value, label, hint }));
}

/** "Started by Tester", or "Started by a pixie" when that pixie is not known. */
export function startedByText(name: string | undefined): string {
  return name === undefined ? "Started by a pixie" : `Started by ${name}`;
}

/** A harness tool's name as words, as the Mac shows it: "start_session" is "Start session". */
export function toolWords(name: string): string {
  const words = name.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
