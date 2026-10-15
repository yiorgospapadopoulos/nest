import { useEffect, useState } from "react";
import type { Restore, RewindPreview } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { ActionSheet } from "../../ui/Sheet.tsx";
import { changes, changesFiles } from "./rewind.ts";

interface Props {
  sessionId: string;
  // The user message to rewind to before.
  eventId: number;
  onClose: () => void;
  onRestore: (restore: Restore) => void;
}

// Loading (undefined), failed (null) or loaded.
type Loaded = RewindPreview | null | undefined;

function codeLine(preview: Loaded): string {
  if (preview === undefined) return "Loading...";
  if (preview === null) return "What would change could not be loaded.";
  return preview.can_rewind
    ? changes(preview)
    : (preview.error ?? "The files cannot be restored to before this message.");
}

/**
 * Rewinds to before a message, like Claude Code's Esc Esc (B59): the conversation (the
 * message and everything after it leave the chat, and the message goes back in the
 * composer), the code (files as they were), or both. Each choice is offered only when its
 * preview says it can be done.
 */
export function RewindSheet({ sessionId, eventId, onClose, onRestore }: Props) {
  const { actions } = useStore();
  const [code, setCode] = useState<Loaded>(undefined);
  const [talk, setTalk] = useState<Loaded>(undefined);

  useEffect(() => {
    let live = true;
    void actions.rewindPreview(sessionId, eventId, "code").then((found) => {
      if (live) setCode(found);
    });
    void actions.rewindPreview(sessionId, eventId, "conversation").then((found) => {
      if (live) setTalk(found);
    });
    return () => {
      live = false;
    };
  }, [actions, sessionId, eventId]);

  const files = changesFiles(code);
  const conversation = talk?.can_rewind === true;
  const choice = (restore: Restore, label: string, enabled: boolean) => (
    <button
      className="asi mid"
      disabled={!enabled}
      onClick={() => {
        onClose();
        onRestore(restore);
      }}
    >
      {label}
    </button>
  );

  return (
    <ActionSheet
      label="Rewind?"
      role="alertdialog"
      onClose={onClose}
      title={
        <>
          <b>Rewind?</b>
          <span className="rwp">{codeLine(code)}</span>
          {talk?.can_rewind === false && (
            <span className="rwp">
              {talk.error ?? "The conversation cannot be rewound to before this message."}
            </span>
          )}
          Restoring the conversation takes this message and everything after it out of the chat, and
          puts the message back in the composer.
        </>
      }
    >
      {choice("conversation", "Restore conversation", conversation)}
      {choice("code", "Restore code", files)}
      {choice("both", "Restore conversation and code", conversation && files)}
    </ActionSheet>
  );
}

interface EditProps {
  // The code preview that found changed files.
  preview: RewindPreview;
  onClose: () => void;
  onEdit: (restore: Restore) => void;
}

/** Editing a message after files changed since it: restore them too, or keep them. */
export function EditSheet({ preview, onClose, onEdit }: EditProps) {
  const pick = (restore: Restore) => () => {
    onClose();
    onEdit(restore);
  };
  return (
    <ActionSheet
      label="Files changed since this message"
      role="alertdialog"
      onClose={onClose}
      title={
        <>
          <b>Files changed since this message</b>
          <span className="rwp">{changes(preview)}</span>
          Editing takes this message and everything after it out of the chat.
        </>
      }
    >
      <button className="asi" onClick={pick("both")}>
        Edit and restore code
      </button>
      <button className="asi" onClick={pick("conversation")}>
        Edit message only
      </button>
    </ActionSheet>
  );
}
