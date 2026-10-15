import { useState, type ReactNode } from "react";
import type { Approval, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { DiffStats } from "../../ui/bits.tsx";
import { Icon, type IconName } from "../../ui/Icon.tsx";
import { DiffSheet, ReviewSummary } from "../approvals/DiffSheet.tsx";
import { usePermission, useReview } from "../approvals/hooks.ts";
import { PlanForm } from "../approvals/PlanForm.tsx";
import { QuestionForm } from "../approvals/QuestionForm.tsx";
import { RemoteConfirmation, ViolationNotice } from "../approvals/ReviewGuards.tsx";
import { Card, SwipeCard } from "../approvals/SwipeCard.tsx";
import { MergeCard } from "./PrCards.tsx";

// With `compose`, the chat opens with its message field focused.
type OpenChat = (sessionId: string, compose?: boolean) => void;

interface Props {
  approval: Approval;
  onOpenChat: OpenChat;
}

export function InboxCard({ approval, onOpenChat }: Props) {
  const { state } = useStore();
  const session = state.sessions[approval.session_id];
  const head = (icon: IconName, kind: string, review = false) => (
    <div className={review ? "ck-k rv" : "ck-k"}>
      <Icon name={icon} />
      {kind}
      <button
        className="lnk"
        onClick={() => {
          onOpenChat(approval.session_id);
        }}
      >
        {session?.title ?? approval.title}
      </button>
    </div>
  );
  switch (approval.kind) {
    case "permission":
      return (
        <PermissionCard approval={approval} session={session} head={head("shield", "Permission")} />
      );
    case "question":
      return (
        <Card label={`Question: ${approval.title}`}>
          {head("q", "Question")}
          <QuestionForm approval={approval} inline={false} />
        </Card>
      );
    case "review":
      return (
        <ReviewCard
          approval={approval}
          session={session}
          head={head("check", "Ready for review", true)}
          onOpenChat={onOpenChat}
        />
      );
    case "plan":
      return (
        <Card label={`Plan: ${approval.title}`}>
          {head("list", "Plan")}
          <PlanForm approval={approval} />
        </Card>
      );
    case "merge":
      return (
        <MergeCard
          approval={approval}
          session={session}
          head={head("branch", "Ready to merge", true)}
        />
      );
  }
}

interface CardProps {
  approval: Approval;
  session: Session | undefined;
  head: ReactNode;
}

function PermissionCard({ approval, session, head }: CardProps) {
  const { view, busy, decide } = usePermission(approval, session);
  return (
    <SwipeCard
      label={`Permission: ${approval.title}`}
      approveLabel="Approve"
      onApprove={() => void decide("allow")}
      onReject={() => void decide("deny")}
      busy={busy}
    >
      {head}
      <div className="cmdbox">{view.command}</div>
      {view.why !== null && <div className="why">{view.why}</div>}
      {view.reason !== null && <div className="why">{view.reason}</div>}
      <div className="acts">
        <button className="b b-ok" disabled={busy} onClick={() => void decide("allow")}>
          <Icon name="check" />
          Approve
        </button>
        <button className="b b-no" disabled={busy} onClick={() => void decide("deny")}>
          Reject
        </button>
        <button className="b qb2" disabled={busy} onClick={() => void decide("allow", true)}>
          Always allow {view.always}
        </button>
      </div>
    </SwipeCard>
  );
}

function ReviewCard({ approval, session, head, onOpenChat }: CardProps & { onOpenChat: OpenChat }) {
  const review = useReview(approval, session);
  // The chat stays open after a reject: go there to say what to change.
  const reject = () =>
    void review.reject(() => {
      onOpenChat(approval.session_id, true);
    });
  const [message, setMessage] = useState(review.title);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [diffOpen, setDiffOpen] = useState(false);
  const fieldId = `commit-${approval.id}`;

  return (
    <>
      <SwipeCard
        label={`Ready for review: ${review.title}`}
        // Unchecked git changes turn a swipe into opening the chat.
        approveLabel={review.blocked ? "Open chat" : review.approveLabel}
        busy={review.busy}
        onApprove={() => {
          // Never publish unchecked git changes with a swipe: show the chat instead.
          if (review.blocked) onOpenChat(approval.session_id);
          // Does nothing until the changes are loaded: nothing is reviewed yet.
          else void review.approve(message);
        }}
        onReject={reject}
      >
        {head}
        <div className="cq">{review.title}</div>
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
        <ViolationNotice review={review} />
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
                className="b b-ok"
                disabled={review.busy || review.blocked || !review.ready}
                onClick={() => void review.approve(message)}
              >
                {review.approveLabel}
              </button>
              <button className="b b-no" disabled={review.busy} onClick={reject}>
                Reject
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
      </SwipeCard>
      {diffOpen && (
        <DiffSheet
          review={review}
          onClose={() => {
            setDiffOpen(false);
          }}
          footer={
            <>
              <button
                className="b b-ok"
                disabled={review.busy || review.blocked || !review.ready}
                onClick={() => void review.approve(message)}
              >
                {review.approveLabel}
              </button>
              <button className="b b-no" disabled={review.busy} onClick={reject}>
                Reject
              </button>
            </>
          }
        />
      )}
      <RemoteConfirmation review={review} />
    </>
  );
}
