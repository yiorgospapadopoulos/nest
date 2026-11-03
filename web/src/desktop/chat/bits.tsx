// Small marks the chat's rows, cards and bars share.

/** "+3 -1" in the review and failed colours. */
export function DiffCounts({
  added,
  removed,
  files,
}: {
  added: number;
  removed: number;
  files?: number;
}) {
  return (
    <span className="dc-ds" aria-label={`${String(added)} added, ${String(removed)} removed`}>
      <span className="add">+{added}</span>
      <span className="del">-{removed}</span>
      {files !== undefined && (
        <span className="dc-dsf">{files === 1 ? "1 file" : `${String(files)} files`}</span>
      )}
    </span>
  );
}

/** The five squares of additions against deletions. */
export function DiffBar({ added, removed }: { added: number; removed: number }) {
  const green = Math.round((added / Math.max(added + removed, 1)) * 5);
  return (
    <span className="dc-dbar" aria-hidden="true">
      {[0, 1, 2, 3, 4].map((index) => (
        <span key={index} className={index < green ? "add" : "del"} />
      ))}
    </span>
  );
}
