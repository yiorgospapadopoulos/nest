import { useEffect, type ReactNode } from "react";
import type { FileDiff, SessionDiff } from "../../api/types.ts";
import { DiffStats } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { Sheet } from "../../ui/Sheet.tsx";
import type { Review } from "./hooks.ts";

interface Props {
  review: Review;
  onClose: () => void;
  // The review actions.
  footer: ReactNode;
}

/** The session's work as a full-screen unified diff, loaded again each time it opens. */
export function DiffSheet({ review, onClose, footer }: Props) {
  const { diff, loadDiff } = review;

  useEffect(() => {
    loadDiff();
  }, [loadDiff]);

  return (
    <Sheet title={review.title} onClose={onClose} full footer={footer}>
      {diff === null &&
        (review.diffFailed ? (
          <p className="note">The changes could not be loaded.</p>
        ) : (
          <p className="note">Loading changes...</p>
        ))}
      {diff !== null && (
        <>
          <ReviewHead diff={diff} commitOnly={review.commitOnly} />
          <div className="dsum">
            <DiffStats {...diff.stats} />
          </div>
          {diff.files.length === 0 && <p className="note">No changes against the base.</p>}
          {diff.files.map((file) => (
            <FileView key={file.path} file={file} />
          ))}
        </>
      )}
    </Sheet>
  );
}

/** On a review card: where approving goes, once loaded. */
export function ReviewSummary({ review }: { review: Review }) {
  if (review.diff !== null) return <ReviewHead diff={review.diff} commitOnly={review.commitOnly} />;
  if (!review.diffFailed) return null;
  return (
    <p className="note">
      The changes could not be loaded.{" "}
      <button className="lnk" onClick={review.loadDiff}>
        Try again
      </button>
    </p>
  );
}

/** Where approving pushes or only commits. */
export function ReviewHead({ diff, commitOnly }: { diff: SessionDiff; commitOnly: boolean }) {
  if (diff.head.branch === null) return null;
  return (
    <p className="dpush">
      <Icon name="branch" />
      {commitOnly ? `Commits to ${diff.head.branch}, not pushed` : `Pushes to ${diff.head.branch}`}
    </p>
  );
}

function FileView({ file }: { file: FileDiff }) {
  const name = file.old_path === null ? file.path : `${file.old_path} → ${file.path}`;
  return (
    <section className="dfile" aria-label={file.path}>
      <div className="dfh">
        <Icon name="file" />
        <span>{name}</span>
      </div>
      {file.binary && <div className="dnote">Binary file</div>}
      {file.nested_repository && <div className="dnote">Nested repository, not committed</div>}
      {file.hunks.map((hunk) => (
        <div key={`${String(hunk.old_start)}-${String(hunk.new_start)}`}>
          <div className="dhh">
            @@ -{hunk.old_start},{hunk.old_lines} +{hunk.new_start},{hunk.new_lines} @@{" "}
            {hunk.header}
          </div>
          {hunk.lines.map((line, i) => {
            const kind = line.kind === "add" ? "a" : line.kind === "delete" ? "d" : "";
            const sign = line.kind === "add" ? "+" : line.kind === "delete" ? "-" : " ";
            return (
              <div key={i} className={`dl ${kind}`}>
                <span>{line.new_line ?? line.old_line}</span>
                <b>{sign}</b>
                <code>{line.text}</code>
              </div>
            );
          })}
        </div>
      ))}
      {file.truncated && <div className="dnote">More lines on the Mac</div>}
    </section>
  );
}
