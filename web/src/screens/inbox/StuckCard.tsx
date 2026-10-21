import type { Session, StuckFlag } from "../../api/types.ts";
import { useStuck } from "../approvals/hooks.ts";
import { FoldRow } from "./FoldRow.tsx";
import { lineText, stuckLine } from "./needsLine.ts";

/** A chat that looks stuck: stop it, or stop it and send a nudge to change course. */
export function StuckCard({
  session,
  stuck,
  onOpenChat,
}: {
  session: Session;
  stuck: StuckFlag;
  onOpenChat: (sessionId: string) => void;
}) {
  const { busy, interrupt, nudge } = useStuck(session.id, stuck.details);
  return (
    <FoldRow
      label={`Stuck: ${session.title}`}
      tone="wait"
      name={session.title}
      onOpen={() => {
        onOpenChat(session.id);
      }}
      line={lineText(stuckLine(stuck))}
    >
      <div className="cq">{stuck.details}</div>
      <div className="acts">
        <button className="b b-pri" disabled={busy} onClick={() => void nudge()}>
          Send a nudge
        </button>
        <button className="b qb2" disabled={busy} onClick={() => void interrupt()}>
          Interrupt
        </button>
      </div>
    </FoldRow>
  );
}
