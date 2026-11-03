import { useEffect, useState } from "react";
import type { Restore } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Button } from "../ui/controls.tsx";
import { Glyph } from "./glyphs.tsx";
import {
  changedCount,
  choices,
  firstChoice,
  reason,
  RESTORE_LABELS,
  RESTORE_SCOPES,
  summary,
  type Loaded,
  type Purpose,
} from "./rewindFlow.ts";
import { Sheet } from "./Sheet.tsx";

const SHOWN_FILES = 8;

interface Props {
  sessionId: string;
  event: number;
  purpose: Purpose;
  onClose: () => void;
  // Rewinds as chosen; resolves once done (false when it failed).
  onRestore: (restore: Restore) => Promise<boolean>;
}

/**
 * Rewind to before a user message, as the Mac's RewindSheet and Claude Code's Esc Esc:
 * restore the conversation, the code or both, with what the code part would change. Edit
 * opens it only when files changed since the message.
 */
export function RewindSheet({ sessionId, event, purpose, onClose, onRestore }: Props) {
  const { actions } = useStore();
  const [code, setCode] = useState<Loaded>(undefined);
  const [talk, setTalk] = useState<Loaded>(undefined);
  const [picked, setPicked] = useState<Restore | null>(null);
  const [restoring, setRestoring] = useState(false);
  useEffect(() => {
    let live = true;
    void Promise.all([
      actions.rewindPreview(sessionId, event, "code", true),
      actions.rewindPreview(sessionId, event, "conversation", true),
    ]).then(([files, conversation]) => {
      if (!live) return;
      setCode(files);
      setTalk(conversation);
    });
    return () => {
      live = false;
    };
  }, [actions, sessionId, event]);
  const loading = code === undefined || talk === undefined;
  const selected = picked ?? (loading ? null : firstChoice(purpose, code, talk));
  const files = code != null && Array.isArray(code.files_changed) ? code.files_changed : [];
  const confirm = () => {
    if (selected === null) return;
    setRestoring(true);
    void onRestore(selected).then((done) => {
      if (done) onClose();
      else setRestoring(false);
    });
  };
  return (
    <Sheet title={purpose === "edit" ? "Edit message" : "Rewind"} onClose={onClose} width={460}>
      <div className="dc-rw">
        <p className="dc-rwq">
          {purpose === "edit"
            ? "Files changed since this message. Restore them too?"
            : "Go back to before this message?"}
        </p>
        {loading ? (
          <p className="dc-rwload">
            <Fireflies size={10} />
            Checking what would change…
          </p>
        ) : (
          <>
            <div role="radiogroup" aria-label="Restore" className="dc-rwopts">
              {choices(purpose).map((restore) => {
                const why = reason(restore, code, talk);
                return (
                  <button
                    key={restore}
                    role="radio"
                    aria-checked={selected === restore}
                    disabled={why !== null}
                    className={selected === restore ? "dc-rwopt on" : "dc-rwopt"}
                    onClick={() => {
                      setPicked(restore);
                    }}
                  >
                    <span className="dc-radio" aria-hidden="true" />
                    <span className="dc-rwoptb">
                      <span>{RESTORE_LABELS[restore]}</span>
                      {why !== null && <span className="dc-rwwhy">{why}</span>}
                    </span>
                  </button>
                );
              })}
            </div>
            {code != null &&
              code.can_rewind &&
              changedCount(code) > 0 &&
              selected !== "conversation" && (
                <div className="dc-rwfiles">
                  <span className="dc-rwsum">{summary(code)}</span>
                  {files.slice(0, SHOWN_FILES).map((path) => (
                    <span key={path} className="dc-rwpath">
                      {path}
                    </span>
                  ))}
                  {files.length > SHOWN_FILES && (
                    <span className="dc-rwwhy">{`and ${String(files.length - SHOWN_FILES)} more`}</span>
                  )}
                </div>
              )}
            {selected !== null && <p className="dc-rwscope">{RESTORE_SCOPES[selected]}</p>}
          </>
        )}
        <div className="dc-sheet-acts">
          <Button onClick={onClose}>Cancel</Button>
          <Button
            kind="destructive"
            disabled={selected === null || restoring}
            data-autofocus
            onClick={confirm}
          >
            <Glyph name="rewind" size={10} />
            {restoring ? "Restoring…" : selected === null ? "Restore" : RESTORE_LABELS[selected]}
          </Button>
        </div>
      </div>
    </Sheet>
  );
}
