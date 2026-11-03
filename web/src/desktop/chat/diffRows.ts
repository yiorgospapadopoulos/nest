// A review's hunk side by side, as NestKit's DiffRows: context on both sides, and within a
// run of changes each removed line beside the added line at the same place.
import type { FileDiff, Hunk } from "../../api/types.ts";

export interface Side {
  number: number | null;
  text: string;
  kind: "context" | "add" | "delete";
}

export interface SplitRow {
  old: Side | null;
  new: Side | null;
}

export function sideBySide(hunk: Hunk): SplitRow[] {
  const rows: SplitRow[] = [];
  let deletes: Side[] = [];
  let adds: Side[] = [];
  const flush = () => {
    const count = Math.max(deletes.length, adds.length);
    for (let i = 0; i < count; i++) rows.push({ old: deletes[i] ?? null, new: adds[i] ?? null });
    deletes = [];
    adds = [];
  };
  for (const line of hunk.lines) {
    if (line.kind === "delete")
      deletes.push({ number: line.old_line, text: line.text, kind: "delete" });
    else if (line.kind === "add")
      adds.push({ number: line.new_line, text: line.text, kind: "add" });
    else {
      flush();
      rows.push({
        old: { number: line.old_line, text: line.text, kind: "context" },
        new: { number: line.new_line, text: line.text, kind: "context" },
      });
    }
  }
  flush();
  return rows;
}

/** "@@ -1,4 +1,6 @@ header" */
export function hunkHeader(hunk: Hunk): string {
  const range = `@@ -${String(hunk.old_start)},${String(hunk.old_lines)} +${String(hunk.new_start)},${String(hunk.new_lines)} @@`;
  return hunk.header === "" ? range : `${range} ${hunk.header}`;
}

/** A file's name, with where it moved from. */
export function fileTitle(file: FileDiff): string {
  return file.old_path === null || file.old_path === file.path
    ? file.path
    : `${file.old_path} → ${file.path}`;
}
