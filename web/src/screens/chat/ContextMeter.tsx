import { useState } from "react";
import type { ContextUsage } from "../../api/types.ts";
import { tokens } from "../../format.ts";
import { ActionSheet } from "../../ui/Sheet.tsx";

interface Props {
  context: ContextUsage;
  disabled: boolean;
  onCompact: () => void;
}

/** A quiet "context 41%" next to the selectors; tapping it offers /compact. */
export function ContextMeter({ context, disabled, onCompact }: Props) {
  const [open, setOpen] = useState(false);
  const percent = String(Math.round(context.percent));
  return (
    <>
      <button
        className="qt ctx"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Context: ${percent}% used`}
        disabled={disabled}
        onClick={() => {
          setOpen(true);
        }}
      >
        context {percent}%
      </button>
      {open && (
        <ActionSheet
          label="Context"
          title={
            <>
              <b>Context</b>
              <span>{`${tokens(context.used)} of ${tokens(context.limit)} tokens`}</span>
            </>
          }
          onClose={() => {
            setOpen(false);
          }}
        >
          <button
            className="asi"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onCompact();
            }}
          >
            <span>
              <span>Compact</span>
              <small>Summarise the conversation so far to free up context</small>
            </span>
          </button>
        </ActionSheet>
      )}
    </>
  );
}
