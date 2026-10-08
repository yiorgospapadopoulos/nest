import { useId } from "react";
import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";
import type { Review } from "./hooks.ts";

/** The agent ran git itself; publishing waits for the switch, as on the Mac. */
export function ViolationNotice({ review }: { review: Review }) {
  const id = useId();
  if (!review.violation) return null;
  return (
    <div className="vio">
      <p>
        <Icon name="shield" />
        The agent ran git itself and changed this chat&apos;s branch. Check its commits before
        publishing.
      </p>
      <div className="vio-r">
        <span id={id}>I checked, publish anyway</span>
        <button
          className="sw"
          role="switch"
          aria-checked={review.acknowledged}
          aria-labelledby={id}
          onClick={() => {
            review.setAcknowledged(!review.acknowledged);
          }}
        />
      </div>
    </div>
  );
}

/** Asks before rejecting, saying what happens to the work, with the Mac's words. */
export function RejectConfirmation({ review }: { review: Review }) {
  if (!review.rejecting) return null;
  return (
    <ActionSheet
      label="Reject this work?"
      role="alertdialog"
      onClose={review.cancelReject}
      title={
        <>
          <b>Reject this work?</b>
          {review.inPlace
            ? "The chat closes. Its changes stay in your folder."
            : "The chat closes and its worktree and branch are removed. Nothing is merged."}
        </>
      }
    >
      <button className="asi dng mid" onClick={() => void review.reject()}>
        Reject
      </button>
    </ActionSheet>
  );
}
