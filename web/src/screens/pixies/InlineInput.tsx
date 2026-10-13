import { useRef, useState } from "react";

interface Props {
  label: string;
  initial: string;
  className: string;
  // A datalist of suggestions.
  list?: string | undefined;
  // The trimmed text when the edit ends; null when it was cancelled (Escape).
  onDone: (text: string | null) => void;
}

/** A field that edits in place: Enter or leaving it ends the edit, Escape cancels it. */
export function InlineInput({ label, initial, className, list, onDone }: Props) {
  const [text, setText] = useState(initial);
  const cancelled = useRef(false);
  return (
    <input
      className={className}
      aria-label={label}
      list={list}
      value={text}
      autoFocus
      autoCapitalize="off"
      autoCorrect="off"
      spellCheck={false}
      onChange={(event) => {
        setText(event.target.value);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          // Not the page's Escape, which goes back.
          event.stopPropagation();
          cancelled.current = true;
        } else if (event.key !== "Enter" || event.nativeEvent.isComposing) {
          return;
        }
        event.preventDefault();
        // Leaving the field ends the edit, once.
        event.currentTarget.blur();
      }}
      onBlur={() => {
        onDone(cancelled.current ? null : text.trim());
      }}
    />
  );
}
