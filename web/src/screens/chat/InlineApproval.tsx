import { useState, type ReactNode } from "react";
import type { Approval, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { engineName } from "../../store/selectors.ts";
import type { InlineAsk } from "../../transcript/build.ts";
import { Dot } from "../../ui/bits.tsx";
import { useMerge, usePermission } from "../approvals/hooks.ts";
import { PlanForm } from "../approvals/PlanForm.tsx";
import { QuestionForm } from "../approvals/QuestionForm.tsx";

interface Props {
  approval: InlineAsk;
  session: Session;
}

/**
 * A pending approval in the transcript, answered in place: a flat card with its kind in the
 * waiting colour, as the Mac's (B102).
 */
export function InlineApproval({ approval, session }: Props) {
  const { state } = useStore();
  switch (approval.kind) {
    case "permission":
      return <InlinePermission approval={approval} session={session} />;
    case "question":
      return (
        <div className="ask" role="group" aria-label="Question">
          <Head>Question from {engineName(state, session.provider)}</Head>
          <QuestionForm approval={approval} inline />
        </div>
      );
    case "plan":
      return (
        <div className="ask pl" role="group" aria-label="Plan ready">
          <Head>Plan</Head>
          <PlanForm approval={approval} />
        </div>
      );
    case "merge":
      return <InlineMerge approval={approval} />;
  }
}

function Head({ children }: { children: ReactNode }) {
  return (
    <div className="ask-h">
      <Dot tone="wait" />
      <span>{children}</span>
    </div>
  );
}

/** Merge, with the choice to delete the chat's branch too, off by default (B96). */
function InlineMerge({ approval }: { approval: Approval }) {
  const { view, busy, merge } = useMerge(approval);
  const [deleteBranch, setDeleteBranch] = useState(false);
  return (
    <div className="ask" role="group" aria-label="Ready to merge">
      <Head>Ready to merge #{view.number}</Head>
      <div className="acts">
        <button className="b b-pri" disabled={busy} onClick={() => void merge(deleteBranch)}>
          Merge (squash)
        </button>
        <a className="b" href={view.url} target="_blank" rel="noreferrer">
          Open on GitHub
        </a>
      </div>
      <label className="ask-ck">
        <input
          type="checkbox"
          checked={deleteBranch}
          onChange={(event) => {
            setDeleteBranch(event.target.checked);
          }}
        />
        Also delete the branch
      </label>
    </div>
  );
}

function InlinePermission({ approval, session }: Props) {
  const { view, busy, decide } = usePermission(approval, session);
  return (
    <div className="ask" role="group" aria-label="Permission needed">
      <Head>Permission needed</Head>
      <div className="cmdbox">{view.command}</div>
      {view.reason !== null && <div className="why">{view.reason}</div>}
      <div className="acts">
        <button className="b b-pri" disabled={busy} onClick={() => void decide("allow")}>
          Approve
        </button>
        <button className="b" disabled={busy} onClick={() => void decide("deny")}>
          Reject
        </button>
        <button className="b plain" disabled={busy} onClick={() => void decide("allow", true)}>
          Always allow {view.always}
        </button>
      </div>
    </div>
  );
}
