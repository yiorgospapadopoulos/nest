import type { RewindPreview } from "../../api/types.ts";

function fileCount(preview: RewindPreview): number {
  const files = preview.files_changed;
  return Array.isArray(files) ? files.length : files;
}

/** Whether restoring the code would change any file. */
export function changesFiles(preview: RewindPreview | null | undefined): boolean {
  return preview?.can_rewind === true && fileCount(preview) > 0;
}

/** What restoring the code would change, in a sentence. */
export function changes(preview: RewindPreview): string {
  const files = preview.files_changed;
  const count = fileCount(preview);
  if (count === 0) return "Nothing to restore. No file changed since this message.";
  const lines = `(+${String(preview.insertions)} -${String(preview.deletions)})`;
  const what =
    count === 1
      ? `1 file goes back to how it was before this message ${lines}`
      : `${String(count)} files go back to how they were before this message ${lines}`;
  return Array.isArray(files) ? `${what}: ${files.join(", ")}.` : `${what}.`;
}
