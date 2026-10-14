import { useId, useState } from "react";
import { useStore } from "../../store/context.ts";
import { Sheet } from "../../ui/Sheet.tsx";

interface Props {
  title: string;
  // The field's label, and the hint shown when it is left empty.
  label: string;
  empty: string;
  initial: string;
  action: string;
  // A handle rather than a name: typed as is, without capitals or corrections.
  code?: boolean;
  // Why the Mac refused the last value, shown under the field.
  refused?: string | null;
  // Called with the trimmed text, never empty.
  onSave: (text: string) => void;
  onClose: () => void;
}

/** A sheet that asks for one short text, such as a team's name or handle. */
export function NameSheet({
  title,
  label,
  empty,
  initial,
  action,
  code = false,
  refused = null,
  onSave,
  onClose,
}: Props) {
  const { actions } = useStore();
  const id = useId();
  const [text, setText] = useState(initial);
  const save = () => {
    const value = text.trim();
    if (value === "") actions.toast(empty, "error");
    else onSave(value);
  };
  return (
    <Sheet
      title={title}
      onClose={onClose}
      leading={
        <button className="done l" onClick={onClose}>
          Cancel
        </button>
      }
      trailing={
        <button className="done" onClick={save}>
          {action}
        </button>
      }
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        <label className="sr" htmlFor={id}>
          {label}
        </label>
        <input
          id={id}
          className="rin2"
          value={text}
          autoComplete="off"
          autoCapitalize={code ? "off" : "words"}
          autoCorrect={code ? "off" : "on"}
          spellCheck={!code}
          data-autofocus
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
        {refused !== null && (
          <p className="pxerr" role="alert">
            {refused}
          </p>
        )}
      </form>
    </Sheet>
  );
}
