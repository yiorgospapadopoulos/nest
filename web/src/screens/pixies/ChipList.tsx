import { useState } from "react";
import { Icon } from "../../ui/Icon.tsx";
import { InlineInput } from "./InlineInput.tsx";
import { usePending } from "./pending.ts";

interface Props {
  // The field's name, also in "Add to <label>" unless `add` names the button.
  label: string;
  add?: string;
  items: string[];
  empty: string;
  // A datalist of suggestions for the field.
  list?: string | undefined;
  save: (items: string[]) => Promise<unknown>;
}

/**
 * Removable chips and a field to add one more, saved as soon as it changes. A quick second
 * change builds on the first, not on the list the Mac has not answered for yet.
 */
export function ChipList({ label, add, items: saved, empty, list, save }: Props) {
  const [adding, setAdding] = useState(false);
  const [items, onChange] = usePending(saved, save);
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
