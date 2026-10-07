import { useEffect, useState, type ReactNode } from "react";
import type { FileDiff, SessionDiff } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { DiffStats } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { Sheet } from "../../ui/Sheet.tsx";

interface Props {
  sessionId: string;
  title: string;
  onClose: () => void;
  // The review actions.
  footer: ReactNode;
}

/** The session's work as a full-screen unified diff. */
export function DiffSheet({ sessionId, title, onClose, footer }: Props) {
  const { actions } = useStore();
  const [diff, setDiff] = useState<SessionDiff | null | "failed">(null);

  useEffect(() => {
    let live = true;
    void actions.diff(sessionId).then((loaded) => {
      if (live) setDiff(loaded ?? "failed");
    });
    return () => {
      live = false;
    };
  }, [actions, sessionId]);

  return (
    <Sheet title={title} onClose={onClose} full footer={footer}>
      {diff === null && <p className="note">Loading changes...</p>}
      {diff === "failed" && <p className="note">The changes could not be loaded.</p>}
      {diff !== null && diff !== "failed" && (
        <>
          <div className="dsum">
            <DiffStats {...diff.stats} />
          </div>
          {diff.files.length === 0 && <p className="note">No changes.</p>}
          {diff.files.map((file) => (
            <FileView key={file.path} file={file} />
          ))}
        </>
      )}
    </Sheet>
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
