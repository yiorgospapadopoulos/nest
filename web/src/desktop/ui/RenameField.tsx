import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

interface Props {
  value: string;
  label: string;
  // The new name, trimmed; never empty and never the old one.
  onCommit: (name: string) => void;
  onCancel: () => void;
  className?: string;
}

/**
 * A name edited in place, as the Mac's inline rename: it opens with the name selected,
 * Enter or leaving the field saves, Escape keeps the old name. An empty or unchanged name
 * saves nothing.
 */
export function RenameField({ value, label, onCommit, onCancel, className }: Props) {
  const [text, setText] = useState(value);
  const field = useRef<HTMLInputElement>(null);
  // Enter saves and then the field's removal blurs it: only the first counts.
  const done = useRef(false);

  useLayoutEffect(() => {
    field.current?.focus({ preventScroll: true });
    field.current?.select();
  }, []);

  const finish = (save: boolean) => {
    if (done.current) return;
    done.current = true;
    const name = text.trim();
    if (save && name !== "" && name !== value) onCommit(name);
    else onCancel();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      finish(event.key === "Enter");
    }
  };

  return (
    <input
      ref={field}
      className={className === undefined ? "dk-rename" : `dk-rename ${className}`}
      aria-label={label}
      value={text}
      spellCheck={false}
      onChange={(event) => {
        setText(event.target.value);
      }}
      onKeyDown={onKeyDown}
      onBlur={() => {
        finish(true);
      }}
      // The row under it would take the press as its own click or drag.
      onPointerDown={(event) => {
        event.stopPropagation();
      }}
      onClick={(event) => {
        event.stopPropagation();
      }}
      draggable={false}
      onDragStart={(event) => {
        event.preventDefault();
        event.stopPropagation();
      }}
    />
  );
}
