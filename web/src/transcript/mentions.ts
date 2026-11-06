import type { Pixie, PixieTeam } from "../api/types.ts";

/** A piece of a user message: plain text, or a mention's name in its pixie's colour. */
export interface MentionPart {
  text: string;
  color: string | null;
}

/** What a mention shows in place of its @ tag. */
export interface MentionLabel {
  name: string;
  color: string;
}

// A whole @ token, as the daemon finds team handles: after the start or a space, and not
// running on into a word character or a hyphen (B40).
const MENTION = /(?<=^|\s)@[a-z0-9-]+(?![\w-])/g;

/** Each pixie slug with its name and colour, and each team handle with its name and its
 * leader's colour. */
export function mentionLabels(
  pixies: Record<string, Pixie>,
  teams: Record<string, PixieTeam>,
): Map<string, MentionLabel> {
  const labels = new Map(
    Object.values(pixies).map((p) => [p.slug, { name: p.name, color: p.color }]),
  );
  for (const team of Object.values(teams)) {
    const color = leaderColor(team, pixies);
    if (color !== null) labels.set(team.handle, { name: team.name, color });
  }
  return labels;
}

/** The team leader's colour, which the team's name and mentions take; null without one. */
export function leaderColor(team: PixieTeam, pixies: Record<string, Pixie>): string | null {
  return pixies[team.leader_id ?? ""]?.color ?? null;
}

/** The text split into plain runs and the mentions `labels` knows, shown as @Name. The sent
 * text keeps its @ tags: that is what calls the pixie. */
export function mentionParts(
  text: string,
  labels: ReadonlyMap<string, MentionLabel>,
): MentionPart[] {
  const parts: MentionPart[] = [];
  let plain = 0;
  for (const match of text.matchAll(MENTION)) {
    const label = labels.get(match[0].slice(1));
    if (label === undefined) continue;
    if (match.index > plain) parts.push({ text: text.slice(plain, match.index), color: null });
    parts.push({ text: `@${label.name}`, color: label.color });
    plain = match.index + match[0].length;
  }
  if (plain < text.length) parts.push({ text: text.slice(plain), color: null });
  return parts;
}
