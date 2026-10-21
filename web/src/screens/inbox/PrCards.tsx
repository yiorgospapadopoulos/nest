import { useState } from "react";
import type { Approval, Session } from "../../api/types.ts";
import type { CiFailure } from "../../store/selectors.ts";
import { useCiFailure, useMerge } from "../approvals/hooks.ts";
import { FoldRow } from "./FoldRow.tsx";
import { checksFailedLine, lineText } from "./needsLine.ts";

function checksText(passed: number): string {
  if (passed === 0) return "No checks";
  return passed === 1 ? "1 check passed" : `${String(passed)} checks passed`;
}

/**
 * A pull request whose checks passed; merging squashes it and closes the chat. The branch
 * stays unless "Also delete the branch" is checked, off by default (B96).
 */
export function MergeDetail({
  approval,
  session,
}: {
  approval: Approval;
  session: Session | undefined;
}) {
  const { view, busy, merge } = useMerge(approval);
  const [deleteBranch, setDeleteBranch] = useState(false);
  const summary = session?.pr_summary ?? null;
  return (
    <>
      {summary !== null && <div className="why prsum">{summary}</div>}
      <div className="why">{checksText(view.passed)}</div>
      <div className="acts">
        <button className="b b-pri" disabled={busy} onClick={() => void merge(deleteBranch)}>
          Merge (squash)
        </button>
        <a className="b qb2" href={view.url} target="_blank" rel="noreferrer">
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
    </>
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
    <FoldRow
      label={`Checks failed: ${session.title}`}
      tone="fail"
      name={session.title}
      onOpen={() => {
        onOpenChat(session.id);
      }}
      line={lineText(checksFailedLine(names))}
    >
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
    </FoldRow>
  );
}
