import type { WorkOf } from "./WorkViews.tsx";

/** A chat's work, as the Mac's work sheet shows it: a subagent's, or a pixie's or team's. */
export type WorkTarget = { session: string } & ({ call: string } | WorkOf);

/**
 * What a transcript page shows: a Nest chat, a Claude Code or Codex chat's history, or the
 * work of a subagent, pixie or team in a chat.
 */
export type TranscriptTarget = { chat: string } | { claude: string } | { work: WorkTarget };

/** The target in a transcript page's address, or null when it names none. */
export function transcriptTarget(query: URLSearchParams): TranscriptTarget | null {
  const value = (name: string) => {
    const found = query.get(name);
    return found === null || found === "" ? null : found;
  };
  const session = value("session");
  if (session !== null) {
    const call = value("call");
    if (call !== null) return { work: { session, call } };
    const pixie = value("pixie");
    if (pixie !== null) return { work: { session, pixie } };
    const team = value("team");
    return team === null ? null : { work: { session, team } };
  }
  const chat = value("chat");
  if (chat !== null) return { chat };
  const claude = value("claude");
  return claude === null ? null : { claude };
}
