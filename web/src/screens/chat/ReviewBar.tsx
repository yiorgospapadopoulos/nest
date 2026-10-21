import { useState } from "react";
import { reviewOf } from "../../api/payloads.ts";
import type { Approval, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { pendingFor } from "../../store/selectors.ts";
import { Icon } from "../../ui/Icon.tsx";
import { DiffSheet } from "../approvals/DiffSheet.tsx";
import { useReview } from "../approvals/hooks.ts";
import { RemoteConfirmation } from "../approvals/ReviewGuards.tsx";

/**
 * "3 files changed +48 -19 · Review" just above the composer while the chat's changes
 * wait for review; Review opens them, to approve from there. Never a card in the chat.
 */
export function ReviewBar({ session }: { session: Session }) {
  const { state } = useStore();
  const pending = pendingFor(state, session.id).find((a) => a.kind === "review");
  if (pending === undefined) return null;
  // A new review starts with its sheet closed.
  return <Bar key={pending.id} approval={pending} session={session} />;
}

function Bar({ approval, session }: { approval: Approval; session: Session }) {
  const [open, setOpen] = useState(false);
  const { files, additions, deletions } = reviewOf(approval);
  return (
    <div className="rvbw">
      <div className="rvbar" role="group" aria-label="Changes to review">
        <Icon name="file" />
        <span className="rvn">
          {files} {files === 1 ? "file" : "files"} changed
        </span>
        <span className="ds">
          <span className="a">+{additions}</span> <span className="d">-{deletions}</span>
        </span>
        <button
          className="b"
          aria-haspopup="dialog"
          onClick={() => {
            setOpen(true);
          }}
        >
          Review
        </button>
      </div>
      {open && (
        <ReviewSheet
          approval={approval}
          session={session}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </div>
  );
}

interface SheetProps {
  approval: Approval;
  session: Session;
  onClose: () => void;
}

/** The changes, approved from the footer once loaded. */
function ReviewSheet({ approval, session, onClose }: SheetProps) {
  const review = useReview(approval, session);
  return (
    <>
      <DiffSheet
        review={review}
        onClose={onClose}
        footer={
          <button
            className="b b-ok"
            disabled={review.busy || !review.ready}
            onClick={() => void review.approve(review.title)}
          >
            {review.approveLabel}
          </button>
        }
      />
      <RemoteConfirmation review={review} />
    </>
  );
}
