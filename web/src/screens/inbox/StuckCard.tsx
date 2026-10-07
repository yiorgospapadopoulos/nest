import type { Session, StuckFlag } from "../../api/types.ts";
import { Icon } from "../../ui/Icon.tsx";
import { useStuck } from "../approvals/hooks.ts";
import { Card } from "../approvals/SwipeCard.tsx";

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
    <Card label={`Stuck: ${session.title}`}>
      <div className="ck-k st">
        <Icon name="stop" />
        Stuck
        <button
          className="lnk"
          onClick={() => {
            onOpenChat(session.id);
          }}
        >
          {session.title}
        </button>
      </div>
      <div className="cq">{stuck.details}</div>
      <div className="acts">
        <button className="b qb2" disabled={busy} onClick={() => void interrupt()}>
          Interrupt
        </button>
        <button className="b b-pri" disabled={busy} onClick={() => void nudge()}>
          Send a nudge
        </button>
      </div>
    </Card>
  );
}
