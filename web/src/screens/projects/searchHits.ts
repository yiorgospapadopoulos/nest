import type { SearchHit } from "../../api/types.ts";

/** One chat's hits, in the order the best of them ranked. */
export interface ChatHits {
  id: string;
  repo: string;
  title: string;
  // A Claude Code chat Nest does not own; it opens read only.
  claude: boolean;
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
        claude: hit.kind === "claude_chat",
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
