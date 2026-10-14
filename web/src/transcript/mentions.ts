import type { Pixie, PixieTeam } from "../api/types.ts";

/** A piece of a user message: plain text, or an @ mention in its pixie's colour. */
export interface MentionPart {
  text: string;
  color: string | null;
}

// A whole @ token, as the daemon finds team handles: after the start or a space, and not
// running on into a word character or a hyphen (B40).
const MENTION = /(?<=^|\s)@[a-z0-9-]+(?![\w-])/g;

/** Each pixie slug with its colour, and each team handle with its leader's. */
export function mentionColors(
  pixies: Record<string, Pixie>,
  teams: Record<string, PixieTeam>,
): Map<string, string> {
  const colors = new Map(Object.values(pixies).map((p) => [p.slug, p.color]));
  for (const team of Object.values(teams)) {
    const leader = pixies[team.leader_id ?? ""];
    if (leader !== undefined) colors.set(team.handle, leader.color);
  }
  return colors;
}

/** The text split into plain runs and the mentions `colors` knows. */
export function mentionParts(text: string, colors: ReadonlyMap<string, string>): MentionPart[] {
  const parts: MentionPart[] = [];
  let plain = 0;
  for (const match of text.matchAll(MENTION)) {
    const color = colors.get(match[0].slice(1));
    if (color === undefined) continue;
    if (match.index > plain) parts.push({ text: text.slice(plain, match.index), color: null });
    parts.push({ text: match[0], color });
    plain = match.index + match[0].length;
  }
  if (plain < text.length) parts.push({ text: text.slice(plain), color: null });
  return parts;
}
