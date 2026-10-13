import type { ReactNode } from "react";
import type { Approval, Session } from "../../api/types.ts";
import type { CiFailure } from "../../store/selectors.ts";
import { Icon } from "../../ui/Icon.tsx";
import { useCiFailure, useMerge } from "../approvals/hooks.ts";
import { Card } from "../approvals/SwipeCard.tsx";

function checksText(passed: number): string {
  if (passed === 0) return "No checks";
  return passed === 1 ? "1 check passed" : `${String(passed)} checks passed`;
}

/** A pull request whose checks passed; merging squashes it and closes the chat. */
export function MergeCard({
  approval,
  session,
  head,
}: {
  approval: Approval;
  session: Session | undefined;
  head: ReactNode;
}) {
  const { view, busy, merge } = useMerge(approval);
  const summary = session?.pr_summary ?? null;
  return (
    <Card label={`Ready to merge: ${approval.title}`}>
      {head}
      <div className="cq">
        #{view.number} {view.title}
      </div>
      {summary !== null && <div className="why prsum">{summary}</div>}
      <div className="why">{checksText(view.passed)}</div>
      <div className="acts">
        <button className="b b-ok" disabled={busy} onClick={() => void merge()}>
          <Icon name="check" />
          Merge (squash)
        </button>
        <a className="b qb2" href={view.url} target="_blank" rel="noreferrer">
          Open on GitHub
        </a>
      </div>
    </Card>
  );
}

/** Checks failed on an open pull request; the agent can be asked to fix them. */
export function CiFailureCard({
  failure,
  onOpenChat,
}: {
  failure: CiFailure;
  onOpenChat: (sessionId: string) => void;
}) {
  const { session, pr, names } = failure;
  const { busy, send } = useCiFailure(session);
  return (
    <Card label={`Checks failed: ${session.title}`}>
      <div className="ck-k fl">
        <Icon name="x" />
        Checks failed
        <button
          className="lnk"
          onClick={() => {
            onOpenChat(session.id);
          }}
        >
          {session.title}
        </button>
      </div>
      <div className="cq">
        #{pr.number} {pr.title}
      </div>
      <ul className="cilist" aria-label="Failing checks">
        {names.map((name) => (
          <li key={name}>{name}</li>
        ))}
      </ul>
      <div className="acts">
        <button className="b b-pri" disabled={busy} onClick={() => void send()}>
          Send to agent
        </button>
        <a className="b qb2" href={pr.url} target="_blank" rel="noreferrer">
          Open on GitHub
        </a>
      </div>
    </Card>
  );
}
