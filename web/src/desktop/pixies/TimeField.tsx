import { useState } from "react";
import { clockText, parseClock } from "./habitText.ts";

const DAY = 24 * 60;

interface Props {
  hour: number;
  minute: number;
  onChange: (hour: number, minute: number) => void;
}

/**
 * A 24 hour time typed as "HH:MM" with a stepper beside it, as the Mac's stepper field
 * in en_GB: the arrows and Up and Down step it a minute; a time it cannot read goes back.
 */
export function TimeField({ hour, minute, onChange }: Props) {
  const shown = clockText(hour, minute);
  // What is typed while the field has the focus.
  const [typed, setTyped] = useState<string | null>(null);
  const step = (by: number) => {
    const total = (((hour * 60 + minute + by) % DAY) + DAY) % DAY;
    setTyped(null);
    onChange(Math.floor(total / 60), total % 60);
  };
  const commit = () => {
    if (typed === null) return;
    const time = parseClock(typed);
    setTyped(null);
    if (time !== null && (time.hour !== hour || time.minute !== minute)) {
      onChange(time.hour, time.minute);
    }
  };
  return (
    <span className="pd-timefield">
      <input
        className="pd-time-field"
        aria-label="At"
        inputMode="numeric"
        spellCheck={false}
        value={typed ?? shown}
        onChange={(event) => {
          setTyped(event.target.value);
        }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
          else if (event.key === "ArrowUp") step(1);
          else if (event.key === "ArrowDown") step(-1);
          else return;
          event.preventDefault();
        }}
      />
      <span className="pd-steps" aria-hidden="true">
        <button
          tabIndex={-1}
          onClick={() => {
            step(1);
          }}
        >
          <svg viewBox="0 0 10 6">
            <path d="M2 4.5 5 1.5l3 3" />
          </svg>
        </button>
        <button
          tabIndex={-1}
          onClick={() => {
            step(-1);
          }}
        >
          <svg viewBox="0 0 10 6">
            <path d="M2 1.5 5 4.5l3-3" />
          </svg>
        </button>
      </span>
    </span>
  );
}
