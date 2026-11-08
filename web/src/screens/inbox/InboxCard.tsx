import { useState, type ReactNode } from "react";
import { commentPlace, reviewCommentsOf } from "../../api/payloads.ts";
import type { Approval, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { DiffStats } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { ApproveButtons, DiffSheet, ReviewSummary } from "../approvals/DiffSheet.tsx";
import { usePermission, useReview, workRoot } from "../approvals/hooks.ts";
import { PlanForm } from "../approvals/PlanForm.tsx";
import { QuestionForm } from "../approvals/QuestionForm.tsx";
import { RemoteConfirmation } from "../approvals/ReviewGuards.tsx";
import { FoldRow } from "./FoldRow.tsx";
import { approvalLine, approvalPixie, lineText } from "./needsLine.ts";
import { Sprite } from "../pixies/Sprite.tsx";
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
  review_comments: "Review comments",
};

/** A pending approval's row: the chat and what it asks, opening to the full item (B102). */
export function InboxCard({ approval, onOpenChat }: Props) {
  const { state } = useStore();
  const session = state.sessions[approval.session_id];
  const green = approval.kind === "review" || approval.kind === "merge";
  const text = lineText(approvalLine(approval, workRoot(session)));
  // Raised inside a pixie call: the pixie's sprite and name before the kind (B114).
  const pixie = approvalPixie(approval, state.pixieGroups[approval.session_id], state.pixies);
  const line =
    pixie === null ? (
      text
    ) : (
      <>
        <span className="npix">
          <Sprite mascot={pixie.mascot} color={pixie.color} size={12} phaseKey={pixie.id} />
          {pixie.name}
        </span>
        {` · ${text}`}
      </>
    );
  return (
    <FoldRow
      label={`${KIND_LABELS[approval.kind]}: ${approval.title}`}
      tone={green ? "rev" : "wait"}
      name={session?.title ?? approval.title}
      onOpen={() => {
        onOpenChat(approval.session_id);
      }}
      line={line}
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
    case "review_comments":
      return <ReviewCommentsDetail approval={approval} />;
  }
}

/**
 * The pull request, each comment's place with Send for it alone over its text, then Send all
 * to agent and Open on GitHub (B101). After a partial send the daemon replaces the approval
 * with one of the rest, so the row stays with those.
 */
function ReviewCommentsDetail({ approval }: { approval: Approval }) {
  const { actions } = useStore();
  const [sending, setSending] = useState<string | null>(null);
  const view = reviewCommentsOf(approval);
  const send = async (key: string, ids?: string[]) => {
    setSending(key);
    await actions.sendReviewComments(approval, ids);
    setSending(null);
  };
  const busy = sending !== null;
  return (
    <>
      <div className="why">
        #{view.number}
        {view.changesRequested && " · Changes requested"}
      </div>
      <ul className="rclist">
        {view.comments.map((comment) => (
          <li key={comment.id}>
            <span className="rch">
              <span className="rcp" title={commentPlace(comment)}>
                {commentPlace(comment, true)}
              </span>
              <button
                className="lnk"
                disabled={busy}
                aria-label={`Send ${commentPlace(comment, true)}`}
                onClick={() => void send(comment.id, [comment.id])}
              >
                Send
              </button>
            </span>
            <span className="rcb">{comment.body}</span>
          </li>
        ))}
      </ul>
      <div className="acts">
        {view.comments.length > 0 && (
          <button className="b b-pri" disabled={busy} onClick={() => void send("all")}>
            <Icon name="send" />
            Send all to agent
          </button>
        )}
        {view.url !== "" && (
          <a className="b qb2" href={view.url} target="_blank" rel="noreferrer">
            Open on GitHub
          </a>
        )}
      </div>
    </>
  );
}

function PermissionDetail({ approval, session }: DetailProps) {
  const { view, busy, decide } = usePermission(approval, session);
  return (
    <>
      <div className="cmdbox">{view.command}</div>
      {view.why !== null && <div className="why">{view.why}</div>}
      {view.reason !== null && <div className="why lines">{view.reason}</div>}
      <div className="acts">
        <button className="b b-pri" disabled={busy} onClick={() => void decide("allow")}>
          Approve
        </button>
        <button className="b" disabled={busy} onClick={() => void decide("deny")}>
          Reject
        </button>
        {view.canAlways && (
          <button className="b qb2" disabled={busy} onClick={() => void decide("allow", true)}>
            Always allow {view.always}
          </button>
        )}
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
            <ApproveButtons review={review} message={message} />
            <button
              className="b qb2"
              onClick={() => {
                setFeedback("");
              }}
            >
              Feedback
            </button>
          </div>
          {review.replyNote !== null && <div className="why">{review.replyNote}</div>}
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
          footer={<ApproveButtons review={review} message={message} />}
        />
      )}
      <RemoteConfirmation review={review} />
    </>
  );
}
