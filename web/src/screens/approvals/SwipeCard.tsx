import type { ReactNode } from "react";
import { Icon } from "../../ui/Icon.tsx";
import { useSwipe } from "./useSwipe.ts";

const HINT_DISTANCE = 20;

interface Props {
  label: string;
  approveLabel: string;
  onApprove: () => void;
  onReject: () => void;
  // An answer is on its way: swipes do nothing, as the buttons are disabled.
  busy: boolean;
  children: ReactNode;
}

/** An Inbox card; swipe right to approve and left to reject, buttons stay the main path. */
export function SwipeCard({ label, approveLabel, onApprove, onReject, busy, children }: Props) {
  const { dx, handlers } = useSwipe(onApprove, onReject, busy);
  const side = dx > HINT_DISTANCE ? " r" : dx < -HINT_DISTANCE ? " l" : "";
  return (
    <div className={`swr${side}`}>
      <div className="swbg" aria-hidden="true">
        <span className="sl">
          <Icon name="check" />
          {approveLabel}
        </span>
        <span className="sr2">
          Reject
          <Icon name="x" />
        </span>
      </div>
      <article
        className={dx === 0 ? "card gl" : "card gl drag"}
        aria-label={label}
        style={
          dx === 0
            ? undefined
            : { transform: `translateX(${String(dx)}px) rotate(${String(dx / 45)}deg)` }
        }
        {...handlers}
      >
        {children}
      </article>
    </div>
  );
}

/** A card that only answers through its buttons, such as a question. */
export function Card({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="swr">
      <article className="card gl" aria-label={label}>
        {children}
      </article>
    </div>
  );
}
