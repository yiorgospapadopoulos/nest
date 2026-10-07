import type { PointerEvent, MouseEvent } from "react";

export interface Suggestion {
  key: string;
  label: string;
  hint: string | null;
  detail: string | null;
  // The message once this is chosen, and where the caret goes.
  result: { text: string; caret: number };
}

interface Props {
  label: string;
  items: Suggestion[];
  active: number;
  onPick: (item: Suggestion) => void;
}

// Keeps focus, and so the iPhone keyboard, in the message field while choosing.
const keepFocus = (event: PointerEvent | MouseEvent) => {
  event.preventDefault();
};

/** Completions for a "/command" or "@path" being typed, just above the composer. */
export function Suggestions({ label, items, active, onPick }: Props) {
  return (
    <div className="sug gl" role="listbox" aria-label={label}>
      {items.map((item, index) => (
        <button
          key={item.key}
          type="button"
          role="option"
          tabIndex={-1}
          aria-selected={index === active}
          className="sgi"
          onPointerDown={keepFocus}
          onMouseDown={keepFocus}
          onClick={() => {
            onPick(item);
          }}
        >
          <span className="sgn">
            {item.label}
            {item.hint !== null && <small> {item.hint}</small>}
          </span>
          {item.detail !== null && <span className="sgd">{item.detail}</span>}
        </button>
      ))}
    </div>
  );
}
