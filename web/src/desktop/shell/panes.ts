// What a workspace pane shows, from its id: a Nest chat (its session id), a new chat's
// draft, a Claude Code chat, a subagent's or a pixie's work in a chat, or, in the Pixies
// tab, a pixie. Tool panes carry their kind as a prefix (layout/workspace.ts).
import type { WorkOf } from "./frame/ChatTree.tsx";

/** What a pane id opens. */
export type PaneTarget =
  | { id: string }
  | { draft: string }
  | { claude: string }
  | { pixie: string }
  | { agentOf: string; call: string }
  | { workOf: string; who: WorkOf };

const DRAFT = "draft:";
const CLAUDE = "claude-code:";
const AGENT = "agent:";
const WORK = "work:";

let drafts = 0;

export function draftPane(): string {
  drafts += 1;
  return `${DRAFT}${String(Date.now())}-${String(drafts)}`;
}

export const isDraft = (pane: string) => pane.startsWith(DRAFT);
export const claudePane = (id: string) => `${CLAUDE}${id}`;
export const agentPane = (session: string, call: string) => `${AGENT}${session}|${call}`;
export const workPane = (session: string, who: WorkOf) =>
  `${WORK}${session}|${"pixie" in who ? `pixie|${who.pixie}` : `team|${who.team}`}`;

/** The chat view a pane id opens; `repo` is where a draft starts its chat. */
export function paneTarget(pane: string, repo: string, pixies: boolean): PaneTarget {
  if (pixies) return { pixie: pane };
  if (isDraft(pane)) return { draft: repo };
  if (pane.startsWith(CLAUDE)) return { claude: pane.slice(CLAUDE.length) };
  if (pane.startsWith(AGENT)) {
    const [agentOf = "", call = ""] = pane.slice(AGENT.length).split("|");
    return { agentOf, call };
  }
  if (pane.startsWith(WORK)) {
    const [workOf = "", kind, id = ""] = pane.slice(WORK.length).split("|");
    return { workOf, who: kind === "team" ? { team: id } : { pixie: id } };
  }
  return { id: pane };
}

/** The sidebar row a pane belongs to: a chat's own, or the chat whose work it shows. */
export function paneRow(pane: string): string {
  if (pane.startsWith(CLAUDE)) return pane;
  if (pane.startsWith(AGENT)) return pane.slice(AGENT.length).split("|")[0] ?? pane;
  if (pane.startsWith(WORK)) return pane.slice(WORK.length).split("|")[0] ?? pane;
  return pane;
}
