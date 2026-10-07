import type { SlashCommand } from "../../api/types.ts";

/** The "/command" or "@path" token being typed at the caret, as Claude Code completes them. */
export interface Trigger {
  kind: "command" | "file";
  // The token's span in the text, from its "/" or "@" to the next whitespace.
  start: number;
  end: number;
  // What was typed after the "/" or "@", up to the caret.
  query: string;
}

const SLASH = /^\/\S*$/;
const MENTION = /(?:^|\s)@\S*$/;

function tokenEnd(text: string, from: number): number {
  const space = text.slice(from).search(/\s/);
  return space === -1 ? text.length : from + space;
}

/** A slash command counts only as the first thing in the message; a mention starts a word. */
export function triggerAt(text: string, caret: number): Trigger | null {
  const before = text.slice(0, caret);
  if (SLASH.test(before)) {
    return { kind: "command", start: 0, end: tokenEnd(text, caret), query: before.slice(1) };
  }
  const mention = MENTION.exec(before);
  if (mention !== null) {
    // The match is "@query", after a whitespace character unless it starts the text.
    const query = mention[0].slice(mention[0].indexOf("@") + 1);
    return { kind: "file", start: caret - query.length - 1, end: tokenEnd(text, caret), query };
  }
  return null;
}

/** The text with `choice` and one space in place of the token, and the caret after them. */
export function replaceTrigger(
  text: string,
  trigger: Trigger,
  choice: string,
): { text: string; caret: number } {
  const head = `${text.slice(0, trigger.start)}${choice} `;
  // A space already after the token is reused rather than doubled.
  const tail = text.slice(trigger.end).replace(/^\s/, "");
  return { text: head + tail, caret: head.length };
}

/** Commands whose name starts with the query first, then those containing it. */
export function matchCommands(commands: SlashCommand[], query: string): SlashCommand[] {
  const q = query.toLowerCase();
  const starts = commands.filter((c) => c.name.toLowerCase().startsWith(q));
  const inside = commands.filter(
    (c) => !c.name.toLowerCase().startsWith(q) && c.name.toLowerCase().includes(q),
  );
  return [...starts, ...inside];
}
