import { useState } from "react";
import { Icon } from "../../ui/Icon.tsx";
import { InlineInput } from "./InlineInput.tsx";

interface Props {
  // The field's name, also in "Add to <label>" unless `add` names the button.
  label: string;
  add?: string;
  items: string[];
  empty: string;
  // A datalist of suggestions for the field.
  list?: string | undefined;
  onChange: (items: string[]) => void;
}

/** Removable chips and a field to add one more, saved as soon as it changes. */
export function ChipList({ label, add, items, empty, list, onChange }: Props) {
  const [adding, setAdding] = useState(false);
  return (
    <div className="pxchips">
      {items.length === 0 && <span className="hint">{empty}</span>}
      {items.map((item) => (
        <span key={item} className="pxchip">
          <code>{item}</code>
          <button
            aria-label={`Remove ${item}`}
            onClick={() => {
              onChange(items.filter((other) => other !== item));
            }}
          >
            <Icon name="x" />
          </button>
        </span>
      ))}
      {adding ? (
        <InlineInput
          label={label}
          initial=""
          className="pxin pxin-sm"
          list={list}
          onDone={(text) => {
            setAdding(false);
            if (text && !items.includes(text)) onChange([...items, text]);
          }}
        />
      ) : (
        <button
          className="pxadd"
          aria-label={add ?? `Add to ${label}`}
          onClick={() => {
            setAdding(true);
          }}
        >
          <Icon name="plus" />
          Add
        </button>
      )}
    </div>
  );
}
