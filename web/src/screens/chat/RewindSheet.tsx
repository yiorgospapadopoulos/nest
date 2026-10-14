import { useEffect, useState } from "react";
import type { RewindPreview } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { ActionSheet } from "../../ui/Sheet.tsx";

interface Props {
  sessionId: string;
  // The user message whose turn the files go back to before.
  eventId: number;
  onClose: () => void;
}

function fileCount(preview: RewindPreview): number {
  const files = preview.files_changed;
  return Array.isArray(files) ? files.length : files;
}

/** What restoring would change, in a sentence. */
function changes(preview: RewindPreview): string {
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

/**
 * Asks before restoring files to before a message, with what would change. Claude Code's
 * file checkpoints restore files only: the conversation stays as it is.
 */
export function RewindSheet({ sessionId, eventId, onClose }: Props) {
  const { actions } = useStore();
  // Loading (undefined), failed (null) or loaded.
  const [preview, setPreview] = useState<RewindPreview | null | undefined>(undefined);

  useEffect(() => {
    let live = true;
    void actions.rewindPreview(sessionId, eventId).then((found) => {
      if (live) setPreview(found);
    });
    return () => {
      live = false;
    };
  }, [actions, sessionId, eventId]);

  const restorable = preview?.can_rewind === true;
  return (
    <ActionSheet
      label="Restore files?"
      role="alertdialog"
      onClose={onClose}
      title={
        <>
          <b>Restore files?</b>
          <span className="rwp">
            {preview === undefined
              ? "Loading..."
              : preview === null
                ? "What would change could not be loaded."
                : preview.can_rewind
                  ? changes(preview)
                  : (preview.error ?? "The files cannot be restored to before this message.")}
          </span>
          Only files are restored. The conversation stays as it is, and Claude is not told.
        </>
      }
    >
      {restorable && (
        <button
          className="asi dng mid"
          disabled={fileCount(preview) === 0}
          onClick={() => {
            onClose();
            void actions.rewind(sessionId, eventId);
          }}
        >
          Restore files
        </button>
      )}
    </ActionSheet>
  );
}
