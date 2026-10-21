import { useState, type ReactNode } from "react";
import type { Approval, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { DiffStats } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { DiffSheet, ReviewSummary } from "../approvals/DiffSheet.tsx";
import { usePermission, useReview, workRoot } from "../approvals/hooks.ts";
import { PlanForm } from "../approvals/PlanForm.tsx";
import { QuestionForm } from "../approvals/QuestionForm.tsx";
import { RemoteConfirmation } from "../approvals/ReviewGuards.tsx";
import { FoldRow } from "./FoldRow.tsx";
import { approvalLine, lineText } from "./needsLine.ts";
import { MergeDetail } from "./PrCards.tsx";

interface Props {
  approval: Approval;
  onOpenChat: (sessionId: string) => void;
}

const KIND_LABELS: Record<Approval["kind"], string> = {
  permission: "Permission",
  question: "Question",
  review: "Ready for review",
  plan: "Plan",
  merge: "Ready to merge",
};

/** A pending approval's row: the chat and what it asks, opening to the full item (B102). */
export function InboxCard({ approval, onOpenChat }: Props) {
  const { state } = useStore();
  const session = state.sessions[approval.session_id];
  const green = approval.kind === "review" || approval.kind === "merge";
  return (
    <FoldRow
      label={`${KIND_LABELS[approval.kind]}: ${approval.title}`}
      tone={green ? "rev" : "wait"}
      name={session?.title ?? approval.title}
      onOpen={() => {
        onOpenChat(approval.session_id);
      }}
      line={lineText(approvalLine(approval, workRoot(session)))}
    >
      <ApprovalDetail approval={approval} session={session} />
    </FoldRow>
  );
}

interface DetailProps {
  approval: Approval;
  session: Session | undefined;
}

function ApprovalDetail({ approval, session }: DetailProps): ReactNode {
  switch (approval.kind) {
    case "permission":
      return <PermissionDetail approval={approval} session={session} />;
    case "question":
      return <QuestionForm approval={approval} inline={false} />;
    case "review":
      return <ReviewDetail approval={approval} session={session} />;
    case "plan":
      return <PlanForm approval={approval} />;
    case "merge":
      return <MergeDetail approval={approval} session={session} />;
  }
}

function PermissionDetail({ approval, session }: DetailProps) {
  const { view, busy, decide } = usePermission(approval, session);
  return (
    <>
      <div className="cmdbox">{view.command}</div>
      {view.why !== null && <div className="why">{view.why}</div>}
      {view.reason !== null && <div className="why">{view.reason}</div>}
      <div className="acts">
        <button className="b b-pri" disabled={busy} onClick={() => void decide("allow")}>
          Approve
        </button>
        <button className="b" disabled={busy} onClick={() => void decide("deny")}>
          Reject
        </button>
        <button className="b qb2" disabled={busy} onClick={() => void decide("allow", true)}>
          Always allow {view.always}
        </button>
      </div>
    </>
  );
}

function ReviewDetail({ approval, session }: DetailProps) {
  const review = useReview(approval, session);
  const [message, setMessage] = useState(review.title);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [diffOpen, setDiffOpen] = useState(false);
  const fieldId = `commit-${approval.id}`;

  return (
    <>
      <div className="crr">
        <DiffStats {...review.view} />
      </div>
      {review.view.summary !== null && <div className="why">{review.view.summary}</div>}
      <button
        className="lnk2"
        onClick={() => {
          setDiffOpen(true);
        }}
      >
        View changes
        <Icon name="chevr" />
      </button>
      <ReviewSummary review={review} />
      {feedback === null ? (
        <>
          <label className="flbl" htmlFor={fieldId}>
            Commit message
          </label>
          <input
            id={fieldId}
            className="fin"
            value={message}
            autoComplete="off"
            onChange={(e) => {
              setMessage(e.target.value);
            }}
          />
          <div className="acts">
            <button
              className="b b-pri"
              disabled={review.busy || !review.ready}
              onClick={() => void review.approve(message)}
            >
              {review.approveLabel}
            </button>
            <button
              className="b qb2"
              onClick={() => {
                setFeedback("");
              }}
            >
              Feedback
            </button>
          </div>
        </>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            // The send button is disabled while the field is blank.
            void review.feedback(feedback.trim());
          }}
        >
          <label className="sr" htmlFor={`${fieldId}-fb`}>
            Feedback
          </label>
          <input
            id={`${fieldId}-fb`}
            className="fin"
            placeholder="Feedback"
            autoComplete="off"
            value={feedback}
            autoFocus
            onChange={(e) => {
              setFeedback(e.target.value);
            }}
          />
          <div className="acts">
            <button className="b b-pri" type="submit" disabled={review.busy || !feedback.trim()}>
              Send feedback
            </button>
            <button
              className="b qb2"
              type="button"
              onClick={() => {
                setFeedback(null);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
      {diffOpen && (
        <DiffSheet
          review={review}
          onClose={() => {
            setDiffOpen(false);
          }}
          footer={
            <button
              className="b b-pri"
              disabled={review.busy || !review.ready}
              onClick={() => void review.approve(message)}
            >
              {review.approveLabel}
            </button>
          }
        />
      )}
      <RemoteConfirmation review={review} />
    </>
  );
}
