import type { Approval, Session } from "../../api/types.ts";
import { ago } from "../../format.ts";
import { workRoot } from "../../screens/approvals/hooks.ts";
import { approvalLine, lineText } from "../../screens/inbox/needsLine.ts";
import { useStore } from "../../store/context.ts";
import { chatStatus, pendingFor, shownTitle } from "../../store/selectors.ts";
import { questionsOf, reviewOf } from "../../api/payloads.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { DiffCounts } from "../chat/bits.tsx";
import { Button } from "../ui/controls.tsx";
import { BOARD_COLUMNS, boardColumns } from "../board.ts";
import { useShell } from "./context.ts";
import "./frame/frame.css";
import { PrChip } from "./frame/PrChip.tsx";

/** The project's chats in four columns, as the Mac's board, over the scanlines. */
export function Board() {
  const { state } = useStore();
  const shell = useShell();
  const columns = boardColumns(state, shell.repo.name);
  return (
    <div className="dk-board">
      {BOARD_COLUMNS.map((column) => (
        <section key={column.id} className="dk-col" aria-label={column.title}>
          <h2 className="dk-colh">
            <span className={`dot s-${column.tone}`} aria-hidden="true" />
            {column.title}
            <span>{columns[column.id].length}</span>
          </h2>
          <div className="dk-colb">
            {columns[column.id].length === 0 && <p className="dk-empty">Nothing here</p>}
            {columns[column.id].map((session) => (
              <BoardCard key={session.id} session={session} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function BoardCard({ session }: { session: Session }) {
  const { state } = useStore();
  const shell = useShell();
  const pending = pendingFor(state, session.id);
  const status = chatStatus(session, pending);
  const approval = pending[0];
  const tasks = (state.tracking[session.id]?.tasks ?? []).filter((t) => t.status !== "deleted");
  const done = tasks.filter((t) => t.status === "completed").length;
  const running = session.state === "running" || session.state === "starting";
  const active = tasks.find((t) => t.status === "in_progress")?.active_form ?? null;
  const colored = ["wait", "rev", "fail"].includes(status.tone);
  return (
    <article className="dk-bcard" aria-label={session.title}>
      <div className="dk-bst">
        <span className={colored ? `dk-bw t-${status.tone}` : "dk-bw"}>{status.label}</span>
        <span>{ago(session.updated_at, new Date())}</span>
      </div>
      <h3 className="dk-bt">{shownTitle(session)}</h3>
      {session.pr !== null && (
        <span className="fr-bpr">
          <PrChip session={session} pr={session.pr} />
        </span>
      )}
      {running ? (
        active !== null && (
          <span className="dk-bline">
            <Fireflies size={9} />
            {active}
          </span>
        )
      ) : approval !== undefined && approval.kind !== "review" && approval.kind !== "merge" ? (
        <span className="dk-bline fr-bwait">
          <Icon
            name={approval.kind === "question" ? "q" : approval.kind === "plan" ? "list" : "shield"}
          />
          {approval.kind === "question"
            ? (questionsOf(approval)[0]?.question ?? approval.title)
            : approval.kind === "plan"
              ? "Plan ready for review"
              : lineText(approvalLine(approval, workRoot(session)))}
        </span>
      ) : (
        approval?.kind === "review" && (
          <span className="dk-bline">
            <ReviewStat approval={approval} />
          </span>
        )
      )}
      {tasks.length > 0 && (
        <span className="dk-bs">{`${String(done)} of ${String(tasks.length)} tasks`}</span>
      )}
      <Button
        className="dk-bopen"
        aria-label={`Open ${session.title}`}
        onClick={() => {
          shell.openChat(session.id);
        }}
      >
        Open
      </Button>
    </article>
  );
}

/** "+48 -19 3 files", as the Mac's DiffStat. */
function ReviewStat({ approval }: { approval: Approval }) {
  const { additions, deletions, files } = reviewOf(approval);
  return <DiffCounts added={additions} removed={deletions} files={files} />;
}
