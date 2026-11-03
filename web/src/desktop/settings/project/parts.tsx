import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button, TextField } from "../../ui/controls.tsx";
import { useOverlay, useRestoreFocus } from "../../ui/floating.ts";
import "../../sheets/sheets.css";
import "../config/config.css";
import "./project.css";

// A project page's controls, as ProjectPage.swift's Chips and AddField and the Mac's
// DropdownMenu and text alert.

/** Small mono chips, each with a remove button; "None yet" while there are none. */
export function Chips({
  items,
  onRemove,
}: {
  items: readonly string[];
  onRemove: (index: number, item: string) => void;
}) {
  if (items.length === 0) return <span className="dkp-none">None yet</span>;
  return (
    <span className="dkp-chips">
      {items.map((item, index) => (
        <span key={`${String(index)}:${item}`} className="dkp-chip">
          <span>{item}</span>
          <button
            type="button"
            title="Remove"
            aria-label={`Remove ${item}`}
            onClick={() => {
              onRemove(index, item);
            }}
          >
            <svg viewBox="0 0 8 8" aria-hidden="true">
              <path d="m1.5 1.5 5 5m0-5-5 5" />
            </svg>
          </button>
        </span>
      ))}
    </span>
  );
}

/** A field with Add on its own line; Return adds too. */
export function AddField({
  placeholder,
  label,
  onAdd,
}: {
  placeholder: string;
  label: string;
  // Whether it was added, which empties the field.
  onAdd: (text: string) => boolean;
}) {
  const [text, setText] = useState("");
  const add = () => {
    if (text.trim() !== "" && onAdd(text)) setText("");
  };
  return (
    <form
      className="dkp-add"
      onSubmit={(event) => {
        event.preventDefault();
        add();
      }}
    >
      <TextField label={label} placeholder={placeholder} value={text} onChange={setText} />
      <Button type="submit" disabled={text.trim() === ""}>
        Add
      </Button>
    </form>
  );
}

/**
 * The Mac's alert with a text field: the title, the field, the line under it, Cancel and
 * Save. Return saves; Escape or Ctrl+W cancels.
 */
export function TextAlert({
  title,
  message,
  placeholder,
  initial,
  onSave,
  onClose,
}: {
  title: string;
  message: string;
  placeholder: string;
  initial: string;
  onSave: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(initial);
  const box = useRef<HTMLFormElement>(null);
  useRestoreFocus();
  useOverlay(onClose);
  useLayoutEffect(() => {
    const field = box.current?.querySelector("input");
    field?.focus({ preventScroll: true });
    field?.select();
  }, []);
  return createPortal(
    <div
      className="dks-alertscrim"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <form
        ref={box}
        className="dks-alert"
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }}
        onSubmit={(event) => {
          event.preventDefault();
          onClose();
          onSave(text);
        }}
      >
        <h2>{title}</h2>
        <p>{message}</p>
        <TextField
          className="dkp-alert-field"
          mono
          label={title}
          placeholder={placeholder}
          value={text}
          onChange={setText}
        />
        <div className="dks-alertb">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" kind="primary">
            Save
          </Button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
