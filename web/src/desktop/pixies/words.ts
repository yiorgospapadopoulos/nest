// The Mac's words and small rules of the Pixies tab (PixiePresentation.swift, PixieTeams.swift,
// PixieTools.swift): the settings' choices, the list's questions, memory facts and skills.
import type { Autonomy, PixieSkill, PixieTeam, ProjectAccess } from "../../api/types.ts";

interface Choice<T extends string> {
  value: T;
  label: string;
  summary: string;
}

export const PROJECT_ACCESS: Choice<ProjectAccess>[] = [
  { value: "edit", label: "Edit", summary: "Reads and edits its projects like any chat" },
  {
    value: "read",
    label: "Read only",
    summary: "Reads its projects, writes only in its own folder",
  },
  { value: "none", label: "None", summary: "Works only in its own folder" },
];

// What its Nest tools may do (B41); the daemon checks it on every call.
export const AUTONOMY: Choice<Autonomy>[] = [
  { value: "observe", label: "Observe", summary: "Reads chats in its projects." },
  { value: "message", label: "Message", summary: "Also writes to them, nudges or stops them." },
  { value: "start", label: "Start", summary: "Also starts chats in their own worktree." },
  {
    value: "answer",
    label: "Answer",
    summary: "Also answers approvals, questions and plans in chats it started.",
  },
];

// How many chats a pixie may run and start, as the daemon allows them.
export const LIMITS = {
  running: { title: "Running chats at once", min: 1, max: 20 },
  perDay: { title: "New chats per day", min: 1, max: 100 },
};

export const ACTIVITY_EMPTY = "Nothing yet. What this pixie does in your chats shows here.";

/** A Nest tool's name as words: "start_session" is "Start session". */
export function toolWords(name: string): string {
  const words = name.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A question the Pixies list asks for typed text: New team, Rename team, Change handle. */
export type TeamPrompt = { kind: "new" } | { kind: "rename" | "handle"; team: string };

export function promptWords(prompt: TeamPrompt): {
  title: string;
  field: string;
  action: string;
  note: string | null;
} {
  switch (prompt.kind) {
    case "new":
      return { title: "New team", field: "Name", action: "Create", note: null };
    case "rename":
      return { title: "Rename team", field: "Name", action: "Rename", note: null };
    case "handle":
      return {
        title: "Change handle",
        field: "Handle",
        action: "Save",
        note: "Lowercase letters, digits and dashes; chats call the team with it.",
      };
  }
}

/** The text the field starts with, selected: the team's name or handle; nothing for a new one. */
export function promptStart(prompt: TeamPrompt, teams: Record<string, PixieTeam>): string {
  if (prompt.kind === "new") return "";
  const team = teams[prompt.team];
  return (prompt.kind === "rename" ? team?.name : team?.handle) ?? "";
}

/** The confirmations of the list's Delete actions, word for word. */
export const CONFIRM = {
  deletePixie: (name: string) => ({
    title: `Delete ${name}?`,
    message: "Its chat, soul and memory go too. This can't be undone.",
  }),
  deleteTeam: (name: string) => ({
    title: `Delete ${name}?`,
    message: "Its pixies stay, without a team.",
  }),
};

// Memory facts: lines of MEMORY.md written as "- YYYY-MM-DD: <fact>".

export interface Fact {
  // The line's index in the file.
  line: number;
  // Empty for a line written without one.
  date: string;
  text: string;
}

const DATED = /^- \d{4}-\d{2}-\d{2}: /;

export function facts(text: string): Fact[] {
  return text.split("\n").flatMap((line, index) => {
    if (!line.startsWith("- ")) return [];
    return DATED.test(line)
      ? [{ line: index, date: line.slice(2, 12), text: line.slice(14) }]
      : [{ line: index, date: "", text: line.slice(2) }];
  });
}

/** The text with a dated fact line at the end. */
export function addingFact(fact: string, text: string, day: string): string {
  const base = text === "" || text.endsWith("\n") ? text : `${text}\n`;
  return `${base}- ${day}: ${fact}\n`;
}

/** The text without the line at `index`. */
export function removingLine(index: number, text: string): string {
  const lines = text.split("\n");
  if (index >= 0 && index < lines.length) lines.splice(index, 1);
  return lines.join("\n");
}

/** Today in the user's time zone, as a fact line writes it. */
export function factDay(date: Date): string {
  const two = (n: number) => String(n).padStart(2, "0");
  return `${String(date.getFullYear())}-${two(date.getMonth() + 1)}-${two(date.getDate())}`;
}

/** "1 fact", "3 facts". */
export function factCount(text: string): string {
  const count = facts(text).length;
  return `${String(count)} ${count === 1 ? "fact" : "facts"}`;
}

// Skills (B85).

/** A plugin's skill without its plugin's name: "code-review:diff" is "diff". */
export function shortName(skill: PixieSkill): string {
  const prefix = skill.plugin === null ? null : `${skill.plugin}:`;
  return prefix !== null && skill.name.startsWith(prefix)
    ? skill.name.slice(prefix.length)
    : skill.name;
}

/** The Add menu: the skills not chosen yet, standalone ones first, then one group per plugin. */
export function skillMenu(
  choices: PixieSkill[],
  chosen: string[],
): {
  standalone: PixieSkill[];
  groups: { plugin: string; skills: PixieSkill[] }[];
  empty: string | null;
} {
  const byName = (a: PixieSkill, b: PixieSkill) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
  const open = choices.filter((c) => !chosen.includes(c.name)).sort(byName);
  const plugins = [...new Set(open.flatMap((c) => (c.plugin === null ? [] : [c.plugin])))].sort();
  const empty =
    open.length > 0
      ? null
      : choices.length > 0
        ? "Every installed skill is added"
        : "No skills installed";
  return {
    standalone: open.filter((c) => c.plugin === null),
    groups: plugins.map((plugin) => ({ plugin, skills: open.filter((c) => c.plugin === plugin) })),
    empty,
  };
}
