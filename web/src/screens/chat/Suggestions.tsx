import type { PointerEvent, MouseEvent } from "react";
import type { Mascot } from "../../api/types.ts";
import { Sprite } from "../pixies/Sprite.tsx";

export interface Suggestion {
  key: string;
  label: string;
  hint: string | null;
  detail: string | null;
  // The message once this is chosen, and where the caret goes.
  result: { text: string; caret: number };
  // After an "@": the section it is listed in, pixies and teams before files (B40).
  group?: "Pixies" | "Files";
  // A pixie's mascot, or a team's members'.
  mascots?: { mascot: Mascot; color: string }[];
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

/**
 * Completions for a "/command" or "@mention" being typed, just above the composer. Mentions
 * are listed in sections; the active one counts across them.
 */
export function Suggestions({ label, items, active, onPick }: Props) {
  const option = (item: Suggestion) => {
    const index = items.indexOf(item);
    return (
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
        {item.mascots !== undefined && (
          <span className="sgm" aria-hidden="true">
            {item.mascots.map((m, at) => (
              <Sprite key={at} mascot={m.mascot} color={m.color} size={18} />
            ))}
          </span>
        )}
        <span className="sgn">
          {item.label}
          {item.hint !== null && <small> {item.hint}</small>}
        </span>
        {item.detail !== null && <span className="sgd">{item.detail}</span>}
      </button>
    );
  };
  const groups = (["Pixies", "Files"] as const).flatMap((group) => {
    const members = items.filter((item) => item.group === group);
    return members.length === 0 ? [] : [{ group, members }];
  });
  return (
    <div className="sug gl" role="listbox" aria-label={label}>
      {groups.length === 0
        ? items.map(option)
        : groups.map(({ group, members }) => (
            <div key={group} role="group" aria-labelledby={`sug-${group}`}>
              <div className="sgh" id={`sug-${group}`}>
                {group}
              </div>
              {members.map(option)}
            </div>
          ))}
    </div>
  );
}
