import type { Session } from "../api/types.ts";
import type { State } from "../store/state.ts";

export type BoardColumn = "running" | "waiting" | "review" | "done";

export const BOARD_COLUMNS: { id: BoardColumn; title: string; tone: string }[] = [
  { id: "running", title: "Running", tone: "run" },
  { id: "waiting", title: "Waiting on you", tone: "wait" },
  { id: "review", title: "Ready for review", tone: "rev" },
  { id: "done", title: "Done", tone: "done" },
];

/**
 * A project's chats as the Mac's board columns: at work, waiting on the user, idle with a
 * review or merge pending, and everything else. Archived and pixie chats are left out.
 */
export function boardColumns(state: State, repo: string): Record<BoardColumn, Session[]> {
  const columns: Record<BoardColumn, Session[]> = {
    running: [],
    waiting: [],
    review: [],
    done: [],
  };
  const reviewing = new Set(
    Object.values(state.approvals)
      .filter((a) => a.kind === "review" || a.kind === "merge")
      .map((a) => a.session_id),
  );
  const sessions = Object.values(state.sessions)
    .filter((s) => s.repo === repo && s.pixie_id == null && s.archived_at === null)
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  for (const session of sessions) {
    const column: BoardColumn =
      session.state === "starting" || session.state === "running"
        ? "running"
        : session.state === "waiting"
          ? "waiting"
          : reviewing.has(session.id)
            ? "review"
            : "done";
    columns[column].push(session);
  }
  return columns;
}
