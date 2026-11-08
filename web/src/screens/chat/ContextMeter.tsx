import { useState } from "react";
import type { ContextUsage, Session } from "../../api/types.ts";
import { tokens } from "../../format.ts";
import { ActionSheet } from "../../ui/Sheet.tsx";
import { useCompactAt } from "./useCompactAt.ts";
import {
  COMPACT_AT_PICKS,
  COMPACT_AT_TITLE,
  compactAtLabel,
  compactAtPick,
  pickedCompactAt,
} from "./options.ts";
import { PickerSheet } from "./PickerSheet.tsx";

interface Props {
  session: Session;
  context: ContextUsage;
  disabled: boolean;
  onCompact: () => void;
}

/**
 * A quiet "41%" of the context used, after the selectors; tapping it offers /compact and,
 * where the engine takes one, the size the chat compacts at by itself (B146).
 */
export function ContextMeter({ session, context, disabled, onCompact }: Props) {
  const [open, setOpen] = useState<"context" | "compactAt" | null>(null);
  const compactAt = useCompactAt(session);
  const percent = String(Math.round(context.percent));
  const close = () => {
    setOpen(null);
  };
  return (
    <>
      <button
        className="qt ctx"
        aria-haspopup="dialog"
        aria-expanded={open !== null}
        aria-label={`Context: ${percent}% used`}
        disabled={disabled}
        onClick={() => {
          setOpen("context");
        }}
      >
        {percent}%
      </button>
      {open === "context" && (
        <ActionSheet
          label="Context"
          title={
            <>
              <b>Context</b>
              <span>{`${tokens(context.used)} of ${tokens(context.limit)} tokens`}</span>
            </>
          }
          onClose={close}
        >
          <button
            className="asi"
            role="menuitem"
            onClick={() => {
              close();
              onCompact();
            }}
          >
            <span>
              <span>Compact</span>
              <small>Summarise the conversation so far to free up context</small>
            </span>
          </button>
          {compactAt !== null && (
            <button
              className="asi"
              role="menuitem"
              aria-haspopup="dialog"
              aria-label={`${COMPACT_AT_TITLE}: ${compactAtLabel(compactAt.value)}`}
              onClick={() => {
                setOpen("compactAt");
              }}
            >
              <span>
                <span>{COMPACT_AT_TITLE}</span>
                <small>{compactAtLabel(compactAt.value)}</small>
              </span>
            </button>
          )}
        </ActionSheet>
      )}
      {open === "compactAt" && compactAt !== null && (
        <PickerSheet
          title={COMPACT_AT_TITLE}
          options={COMPACT_AT_PICKS}
          value={compactAtPick(compactAt.value)}
          onPick={(value) => {
            compactAt.pick(pickedCompactAt(value));
          }}
          onClose={close}
        />
      )}
    </>
  );
}
