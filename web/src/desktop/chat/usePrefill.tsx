import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Attachment } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { NO_DRAFT, type Draft } from "../../store/state.ts";
import { Button } from "../ui/controls.tsx";
import { focusComposer } from "./composerFocus.ts";
import { Sheet } from "./Sheet.tsx";

/** A message taken back into the composer: a pending one edited, or a rewound one (B59). */
export interface TakenBack {
  text: string;
  files: Attachment[];
}

/**
 * Puts a message taken back into the draft under `key` and focuses the composer. A draft
 * that holds something asks first, as the Mac's alert: Replace, or Keep both, which puts
 * the message before the draft.
 */
export function usePrefill(key: string): { fill: (taken: TakenBack) => void; ask: ReactNode } {
  const { state, actions } = useStore();
  const [asking, setAsking] = useState<TakenBack | null>(null);
  const draft = useRef<Draft>(NO_DRAFT);
  const current = state.drafts[key] ?? NO_DRAFT;
  useEffect(() => {
    draft.current = current;
  }, [current]);

  const put = ({ text, files }: TakenBack) => {
    actions.fillDraft(key, text, files);
    focusComposer(key);
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
    <Sheet title="Replace your draft?" onClose={close} width={380}>
      <p className="dc-alert">
        The message you took back goes into the composer. Keep both puts it before your draft.
      </p>
      <div className="dc-sheet-acts">
        <Button
          onClick={() => {
            close();
            const { text, files } = draft.current;
            const both = [asking.text.trimEnd(), text].filter((part) => part !== "").join("\n\n");
            put({ text: both, files: [...asking.files, ...files] });
          }}
        >
          Keep both
        </Button>
        <Button
          kind="primary"
          data-autofocus
          onClick={() => {
            close();
            put(asking);
          }}
        >
          Replace
        </Button>
      </div>
    </Sheet>
  );
  return { fill, ask };
}
