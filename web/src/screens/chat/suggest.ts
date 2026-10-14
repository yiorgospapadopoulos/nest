import type { Mascot, Pixie, SlashCommand } from "../../api/types.ts";
import type { CallableTeam } from "../../store/selectors.ts";

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

/** A pixie or team offered after an "@", before the text it would insert is known. */
export interface PixieMention {
  key: string;
  label: string;
  hint: string;
  detail: string | null;
  group: "Pixies";
  mascots: { mascot: Mascot; color: string }[];
  // The slug or handle the mention inserts.
  handle: string;
}

const look = ({ mascot, color }: Pixie) => ({ mascot, color });

/** The first non-empty line of a soul, without Markdown heading marks. */
export function soulLine(text: string): string {
  const line = text.split("\n").find((each) => each.trim() !== "") ?? "";
  return line.replace(/^\s*#+\s*/, "").trim();
}

/** Teams, then pixies, whose name or handle contains the query (any case). */
export function pixieMentions(
  teams: CallableTeam[],
  pixies: Pixie[],
  souls: Record<string, string>,
  query: string,
): PixieMention[] {
  const q = query.toLowerCase();
  const matches = (name: string, handle: string) =>
    name.toLowerCase().includes(q) || handle.includes(q);
  return [
    ...teams
      .filter(({ team }) => matches(team.name, team.handle))
      .map(({ team, members }) => ({
        key: `team:${team.id}`,
        label: team.name,
        hint: `@${team.handle}`,
        detail: null,
        group: "Pixies" as const,
        mascots: members.map(look),
        handle: team.handle,
      })),
    ...pixies
      .filter((p) => matches(p.name, p.slug))
      .map((p) => ({
        key: `pixie:${p.id}`,
        label: p.name,
        hint: `@${p.slug}`,
        detail: souls[p.id] ?? null,
        group: "Pixies" as const,
        mascots: [look(p)],
        handle: p.slug,
      })),
  ];
}
