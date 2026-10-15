import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Attachment } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { NO_DRAFT, type Draft } from "../../store/state.ts";
import { ActionSheet } from "../../ui/Sheet.tsx";

/** A message taken back into the composer: a pending one edited, or a rewound one (B59). */
export interface TakenBack {
  text: string;
  files: Attachment[];
}

function focusComposer() {
  // After any sheet closed and gave focus back to what opened it.
  setTimeout(() => {
    document.getElementById("composer")?.focus();
  }, 0);
}

/**
 * Puts a message taken back into the draft under `key` and focuses the composer. A draft
 * that already holds something is replaced only if the user says so, or kept with the
 * message added after it.
 */
export function usePrefill(key: string): { fill: (taken: TakenBack) => void; ask: ReactNode } {
  const { state, actions } = useStore();
  const [asking, setAsking] = useState<TakenBack | null>(null);
  // The draft as it is when the message comes back, after an await.
  const draft = useRef<Draft>(NO_DRAFT);
  const current = state.drafts[key] ?? NO_DRAFT;
  useEffect(() => {
    draft.current = current;
  }, [current]);

  const put = ({ text, files }: TakenBack) => {
    actions.fillDraft(key, text, files);
    focusComposer();
  };

  const fill = (taken: TakenBack) => {
    const { text, files } = draft.current;
    if (text.trim() === "" && files.length === 0) put(taken);
    else setAsking(taken);
  };

  const close = () => {
    setAsking(null);
  };

  const ask = asking !== null && (
    <ActionSheet
      label="Replace your message?"
      role="alertdialog"
      onClose={close}
      title={
        <>
          <b>Replace your message?</b>
          The composer already has a message in it.
        </>
      }
    >
      <button
        className="asi"
        onClick={() => {
          close();
          put(asking);
        }}
      >
        Replace
      </button>
      <button
        className="asi"
        onClick={() => {
          close();
          const { text, files } = draft.current;
          const both = [text.trimEnd(), asking.text].filter(Boolean).join("\n\n");
          put({ text: both, files: [...files, ...asking.files] });
        }}
      >
        Keep both
      </button>
    </ActionSheet>
  );
  return { fill, ask };
}
