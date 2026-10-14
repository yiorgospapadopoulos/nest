import { useId, useState } from "react";
import type { Pixie, UpdatePixieBody } from "../../api/types.ts";

type Limit = "max_running" | "max_per_day";

const LIMITS: readonly { key: Limit; title: string; max: number }[] = [
  { key: "max_running", title: "Running chats at once", max: 20 },
  { key: "max_per_day", title: "New chats per day", max: 100 },
];

interface Props {
  pixie: Pixie;
  save: (body: UpdatePixieBody) => Promise<boolean>;
}

/** How many chats the pixie may start (B41): running at once, and new each local day. */
export function PixieLimits({ pixie, save }: Props) {
  return (
    <div className="lgrp gl">
      {LIMITS.map(({ key, title, max }) => (
        <Stepper
          key={key}
          title={title}
          value={pixie[key]}
          max={max}
          save={(value) => save({ [key]: value })}
        />
      ))}
    </div>
  );
}

interface StepperProps {
  title: string;
  value: number;
  max: number;
  save: (value: number) => Promise<boolean>;
}

/**
 * A number from 1 to `max` with Fewer and More. Each step is saved; while steps are being
 * saved the stepped number shows, then the saved one (the last step, or the old value
 * when the Mac refused).
 */
function Stepper({ title, value, max, save }: StepperProps) {
  const id = useId();
  const [stepped, setStepped] = useState(value);
  const [saving, setSaving] = useState(0);
  const shown = saving > 0 ? stepped : value;
  const step = (by: number) => {
    const next = shown + by;
    setStepped(next);
    setSaving((n) => n + 1);
    void save(next).finally(() => {
      setSaving((n) => n - 1);
    });
  };
  return (
    <div className="srow">
      <span id={id}>{title}</span>
      <span className="pxnum" role="group" aria-labelledby={id}>
        <button
          aria-label="Fewer"
          disabled={shown <= 1}
          onClick={() => {
            step(-1);
          }}
        >
          −
        </button>
        <output>{shown}</output>
        <button
          aria-label="More"
          disabled={shown >= max}
          onClick={() => {
            step(1);
          }}
        >
          +
        </button>
      </span>
    </div>
  );
}
