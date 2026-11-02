import { useStore } from "../../store/context.ts";
import { pendingFor } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { reviewWaitingLine, type GitHubPart } from "../../transcript/github.ts";

/**
 * The part of a user bubble Nest wrote from GitHub (B101): a grey first line, then the
 * issue's title, a few lines of its body and its comment count, or each review comment's
 * place in mono over its text. As the Mac's bubble.
 */
export function GitHubText({ part }: { part: GitHubPart }) {
  return (
    <span className="ghp">
      <span className="ghq">{part.header}</span>
      {part.kind === "issue" ? (
        <>
          <b>{part.title}</b>
          {part.excerpt !== "" && <span className="ghx">{part.excerpt}</span>}
          {part.comments !== null && <span className="ghq">{part.comments}</span>}
        </>
      ) : (
        part.items.map((item, i) => (
          <span key={i} className="ghi">
            <span className="ghq ghm">{item.place}</span>
            <span>{item.text}</span>
          </span>
        ))
      )}
    </span>
  );
}

/** "Review on #49: 3 comments. See Needs you", grey with the waiting dot (B101). */
export function ReviewWaitingLine({ sessionId }: { sessionId: string }) {
  const { state } = useStore();
  const waiting = pendingFor(state, sessionId).find((a) => a.kind === "review_comments");
  if (waiting === undefined) return null;
  return (
    <div className="rvwait">
      <Dot tone="wait" />
      {reviewWaitingLine(waiting)}
    </div>
  );
}
