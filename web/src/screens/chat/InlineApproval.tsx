import { useState } from "react";
import type { Approval, Session } from "../../api/types.ts";
import { DiffStats } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { DiffSheet } from "../approvals/DiffSheet.tsx";
import { useMerge, usePermission, useReview } from "../approvals/hooks.ts";
import { PlanForm } from "../approvals/PlanForm.tsx";
import { QuestionForm } from "../approvals/QuestionForm.tsx";

interface Props {
  approval: Approval;
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
    case "review":
      return <InlineReview approval={approval} session={session} />;
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
      <div className="acts">
        <button className="b b-ok" disabled={busy} onClick={() => void decide("allow")}>
          Approve
        </button>
        <button className="b b-no" disabled={busy} onClick={() => void decide("deny")}>
          Reject
        </button>
      </div>
    </div>
  );
}

function InlineReview({ approval, session }: Props) {
  const review = useReview(approval, session);
  const [diffOpen, setDiffOpen] = useState(false);
  const approve = () => void review.approve(review.title);
  return (
    <div className="ask rv" role="group" aria-label="Ready for review">
      <div className="ask-h">
        <Icon name="check" />
        Ready for review
      </div>
      <div className="crr">
        <DiffStats {...review.view} />
      </div>
      <div className="acts">
        <button className="b b-ok" disabled={review.busy} onClick={approve}>
          {review.approveLabel}
        </button>
        <button
          className="b"
          onClick={() => {
            setDiffOpen(true);
          }}
        >
          View changes
        </button>
      </div>
      {diffOpen && (
        <DiffSheet
          sessionId={session.id}
          title={review.title}
          onClose={() => {
            setDiffOpen(false);
          }}
          footer={
            <>
              <button className="b b-ok" disabled={review.busy} onClick={approve}>
                {review.approveLabel}
              </button>
              <button
                className="b b-no"
                disabled={review.busy}
                onClick={() => void review.reject()}
              >
                Reject
              </button>
            </>
          }
        />
      )}
    </div>
  );
}
