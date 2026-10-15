import type { Approval, Session } from "../../api/types.ts";
import type { InlineAsk } from "../../transcript/build.ts";
import { Icon } from "../../ui/Icon.tsx";
import { useMerge, usePermission } from "../approvals/hooks.ts";
import { PlanForm } from "../approvals/PlanForm.tsx";
import { QuestionForm } from "../approvals/QuestionForm.tsx";

interface Props {
  approval: InlineAsk;
  session: Session;
}

/** A pending approval in the transcript, answered in place. */
export function InlineApproval({ approval, session }: Props) {
  switch (approval.kind) {
    case "permission":
      return <InlinePermission approval={approval} session={session} />;
    case "question":
      return (
        <div className="ask" role="group" aria-label="Question">
          <div className="ask-h">
            <Icon name="q" />
            Question
          </div>
          <QuestionForm approval={approval} inline />
        </div>
      );
    case "plan":
      return (
        <div className="ask pl" role="group" aria-label="Plan ready">
          <div className="ask-h">
            <Icon name="list" />
            Plan
          </div>
          <PlanForm approval={approval} />
        </div>
      );
    case "merge":
      return <InlineMerge approval={approval} />;
  }
}

function InlineMerge({ approval }: { approval: Approval }) {
  const { view, busy, merge } = useMerge(approval);
  return (
    <div className="ask" role="group" aria-label="Ready to merge">
      <div className="ask-h">
        <Icon name="branch" />
        Ready to merge #{view.number}
      </div>
      <div className="acts">
        <button className="b b-ok" disabled={busy} onClick={() => void merge()}>
          Merge (squash)
        </button>
        <a className="b qb2" href={view.url} target="_blank" rel="noreferrer">
          Open on GitHub
        </a>
      </div>
    </div>
  );
}

function InlinePermission({ approval, session }: Props) {
  const { view, busy, decide } = usePermission(approval, session);
  return (
    <div className="ask" role="group" aria-label="Permission needed">
      <div className="ask-h">
        <Icon name="shield" />
        Permission needed
      </div>
      <div className="cmdbox">{view.command}</div>
      {view.reason !== null && <div className="why">{view.reason}</div>}
      <div className="acts">
        <button className="b b-ok" disabled={busy} onClick={() => void decide("allow")}>
          Approve
        </button>
        <button className="b b-no" disabled={busy} onClick={() => void decide("deny")}>
          Reject
        </button>
        <button className="b qb2" disabled={busy} onClick={() => void decide("allow", true)}>
          Always allow {view.always}
        </button>
      </div>
    </div>
  );
}
