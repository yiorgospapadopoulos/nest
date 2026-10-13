import type { Autonomy, Mascot, PixieBackground, ProjectAccess } from "../../api/types.ts";
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

// Stored now; the harness tools that use it come with stage 3 (D057).
export const AUTONOMY: Record<Autonomy, Choice> = {
  observe: { label: "Observe", hint: "Reads chats, the inbox and pull requests" },
  message: { label: "Message", hint: "Also sends messages and nudges to chats" },
  start: { label: "Start", hint: "Also starts and closes chats of its own" },
  answer: { label: "Answer", hint: "Also answers permissions, questions and plans" },
};

/** A picker's options, in the order the choices are listed. */
export function optionsOf(choices: Record<string, Choice>): Option<string>[] {
  return Object.entries(choices).map(([value, { label, hint }]) => ({ value, label, hint }));
}
