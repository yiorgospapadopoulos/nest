import { useState } from "react";
import { NameSheet } from "../pixies/NameSheet.tsx";
import { Row } from "./rows.tsx";

/** A row with a short text in mono, or `unset` while there is none, and Change; empty is allowed. */
export function TextRow({
  label,
  value,
  unset,
  disabled = false,
  onSave,
}: {
  label: string;
  value: string | null;
  unset: string;
  disabled?: boolean;
  // The trimmed text, empty when the field was cleared.
  onSave: (text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <Row label={label}>
      <span className={value === null ? "sval" : "sval mono"}>{value ?? unset}</span>
      <button
        className="b"
        aria-label={`Change ${label}`}
        disabled={disabled}
        onClick={() => {
          setEditing(true);
        }}
      >
        Change
      </button>
      {editing && (
        <NameSheet
          title={label}
          label={label}
          empty={null}
          initial={value ?? ""}
          action="Save"
          code
          onSave={(text) => {
            setEditing(false);
            onSave(text);
          }}
          onClose={() => {
            setEditing(false);
          }}
        />
      )}
    </Row>
  );
}
