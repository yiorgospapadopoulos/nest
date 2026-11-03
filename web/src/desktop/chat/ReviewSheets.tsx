// A review's changes, as the Mac's DiffSheet: side by side or unified, file by file, with
// Approve in the footer, which opens the PublishSheet.
import { useEffect, useState } from "react";
import type { FileDiff, Hunk, SessionDiff } from "../../api/types.ts";
import { COMMIT_TITLE, type Review } from "../../screens/approvals/hooks.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Button, Segmented } from "../ui/controls.tsx";
import { DiffCounts } from "./bits.tsx";
import { fileTitle, hunkHeader, sideBySide, type Side } from "./diffRows.ts";
import { Disclosure, Glyph } from "./glyphs.tsx";
import { Sheet } from "./Sheet.tsx";

type Layout = "split" | "unified";

/** Where approving pushes, or that it only commits. */
export function PublishTarget({ diff, pushes }: { diff: SessionDiff; pushes: boolean }) {
  const branch = diff.head.branch;
  if (branch === null) return null;
  return (
    <p className="dc-target">
      <Glyph name={pushes ? "pr" : "branch"} size={10} />
      {pushes ? `Pushes to ${branch}` : `Commits to ${branch}, not pushed`}
    </p>
  );
}

interface DiffProps {
  review: Review;
  onClose: () => void;
  // Approve from the footer: the publish sheet, or with `commitOnly` the commit only.
  onApprove: (commitOnly: boolean) => void;
}

/** The changes, read again on every opening; Approve waits for them. */
export function DiffSheet({ review, onClose, onApprove }: DiffProps) {
  const [layout, setLayout] = useState<Layout>("split");
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const { diff, loadDiff } = review;
  useEffect(() => {
    loadDiff();
  }, [loadDiff]);
  const toggle = (path: string) => {
    const next = new Set(collapsed);
    if (!next.delete(path)) next.add(path);
    setCollapsed(next);
  };
  return (
    <Sheet title="Changes" onClose={onClose} large bare>
      <div className="dc-diffh">
        <div className="dc-diffht">
          <h2>Changes</h2>
          <span>{review.title}</span>
        </div>
        {diff !== null && (
          <DiffCounts
            added={diff.stats.additions}
            removed={diff.stats.deletions}
            files={diff.stats.files}
          />
        )}
        <Segmented
          label="Layout"
          value={layout}
          options={[
            { value: "split", label: "Side by side" },
            { value: "unified", label: "Unified" },
          ]}
          onChange={setLayout}
        />
        <button className="dk-btn k-plain icon" aria-label="Close changes" onClick={onClose}>
          <Glyph name="close" size={10} />
        </button>
      </div>
      <div className="dc-diffb">
        {diff === null ? (
          review.diffFailed ? (
            <p className="dc-diffnote bad">Could not load the changes.</p>
          ) : (
            <div className="dc-diffnote">
              <Fireflies size={14} />
            </div>
          )
        ) : (
          <>
            <PublishTarget diff={diff} pushes={!review.commitOnly} />
            {diff.files.length === 0 && <p className="dc-diffnote">No changes against the base.</p>}
            {diff.files.map((file) => (
              <FileSection
                key={file.path}
                file={file}
                layout={layout}
                collapsed={collapsed.has(file.path)}
                onToggle={() => {
                  toggle(file.path);
                }}
              />
            ))}
          </>
        )}
      </div>
      <div className="dc-difff">
        {review.offersCommitOnly && (
          <Button
            kind="plain"
            disabled={!review.ready}
            title="Commit without pushing; the pull request stays as it is"
            onClick={() => {
              onApprove(true);
            }}
          >
            {COMMIT_TITLE}
          </Button>
        )}
        <Button
          kind="primary"
          disabled={!review.ready}
          onClick={() => {
            onApprove(false);
          }}
        >
          <Glyph name={review.commitOnly ? "check" : "pr"} size={10} />
          {review.approveLabel}
        </Button>
      </div>
    </Sheet>
  );
}

function FileSection({
  file,
  layout,
  collapsed,
  onToggle,
}: {
  file: FileDiff;
  layout: Layout;
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <section className="dc-dfile" aria-label={file.path}>
      <button className="dc-dfileh" aria-expanded={!collapsed} onClick={onToggle}>
        <Disclosure open={!collapsed} />
        <span className="dc-dfilen">{fileTitle(file)}</span>
        {file.status !== "modified" && (
          <span className="dc-dfiles">
            {file.status.charAt(0).toUpperCase() + file.status.slice(1)}
          </span>
        )}
        <span className="grow" />
        {!file.binary && <DiffCounts added={file.additions} removed={file.deletions} />}
      </button>
      {!collapsed && (
        <div className="dc-dfileb">
          {file.nested_repository ? (
            <p className="dc-dnote">A nested repository: shown, but never committed.</p>
          ) : file.binary ? (
            <p className="dc-dnote">Binary file, not shown</p>
          ) : (
            file.hunks.length === 0 && <p className="dc-dnote">No line changes</p>
          )}
          {file.hunks.map((hunk) => (
            <div key={`${String(hunk.old_start)}-${String(hunk.new_start)}`}>
              <div className="dc-dhh">{hunkHeader(hunk)}</div>
              {layout === "unified" ? <Unified hunk={hunk} /> : <Split hunk={hunk} />}
            </div>
          ))}
          {file.truncated && (
            <p className="dc-dnote">The rest of this file is too long to show here.</p>
          )}
        </div>
      )}
    </section>
  );
}

const SIGNS = { add: "+", delete: "-", context: " " } as const;

function Unified({ hunk }: { hunk: Hunk }) {
  return (
    <div className="dc-dhunk">
      {hunk.lines.map((line, index) => (
        <div key={index} className={`dc-drow ${line.kind}`}>
          <span className="dc-dn">{line.old_line ?? ""}</span>
          <span className="dc-dn">{line.new_line ?? ""}</span>
          <span className="dc-dsign">{SIGNS[line.kind]}</span>
          <span className="dc-dtext">{line.text}</span>
        </div>
      ))}
    </div>
  );
}

function SideCell({ side }: { side: Side | null }) {
  if (side === null) return <div className="dc-dcell empty" />;
  return (
    <div className={`dc-dcell ${side.kind}`}>
      <span className="dc-dn">{side.number ?? ""}</span>
      <span className="dc-dsign">{SIGNS[side.kind]}</span>
      <span className="dc-dtext">{side.text}</span>
    </div>
  );
}

function Split({ hunk }: { hunk: Hunk }) {
  return (
    <div className="dc-dhunk split">
      {sideBySide(hunk).map((row, index) => (
        <div key={index} className="dc-dsplit">
          <SideCell side={row.old} />
          <SideCell side={row.new} />
        </div>
      ))}
    </div>
  );
}
