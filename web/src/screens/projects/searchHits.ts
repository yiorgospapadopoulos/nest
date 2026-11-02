import type { SearchHit } from "../../api/types.ts";

const OUTSIDE_ENGINES: Partial<Record<SearchHit["kind"], string>> = {
  claude_chat: "Claude Code",
  codex_chat: "Codex",
};

/** One chat's hits, in the order the best of them ranked. */
export interface ChatHits {
  id: string;
  repo: string;
  title: string;
  // For a Claude Code or Codex chat Nest does not own, its engine by name; it opens read
  // only. Null for a Nest chat.
  engine: string | null;
  // The title match, if the title matched.
  titleHit: SearchHit | null;
  // Message matches, best first.
  hits: SearchHit[];
}

export function groupHits(hits: SearchHit[]): ChatHits[] {
  const groups = new Map<string, ChatHits>();
  for (const hit of hits) {
    let group = groups.get(hit.session_id);
    if (group === undefined) {
      group = {
        id: hit.session_id,
        repo: hit.repo,
        title: hit.title,
        engine: OUTSIDE_ENGINES[hit.kind] ?? null,
        titleHit: null,
        hits: [],
      };
      groups.set(hit.session_id, group);
    }
    if (hit.event_id === null) group.titleHit = hit;
    else group.hits.push(hit);
  }
  return [...groups.values()];
}
