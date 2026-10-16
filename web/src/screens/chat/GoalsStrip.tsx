import { useState } from "react";
import type { TrackedTask } from "../../api/types.ts";
import { Checklist } from "../../ui/Checklist.tsx";
import { Icon } from "../../ui/Icon.tsx";

/** The agent's task list: the current step with progress, expanding to the checklist. */
export function GoalsStrip({ tasks }: { tasks: TrackedTask[] }) {
  const [open, setOpen] = useState(false);
  const shown = tasks.filter((t) => t.status !== "deleted");
  // It comes back collapsed.
  if (shown.length === 0 && open) setOpen(false);
  if (shown.length === 0) return null;
  const done = shown.filter((t) => t.status === "completed").length;
  const current =
    shown.find((t) => t.status === "in_progress") ?? shown.find((t) => t.status === "pending");
  const heading = current === undefined ? "All done" : `Now: ${current.subject}`;
  const percent = Math.round((done / shown.length) * 100);

  return (
    <div className="gs gl">
      <button
        className="gs-h"
        aria-expanded={open}
        aria-controls="goals-list"
        onClick={() => {
          setOpen(!open);
        }}
      >
        <Icon name="list" />
        <span className="gs-t">{heading}</span>
        <span className="gs-n">
          {done} of {shown.length}
        </span>
        <Icon name="chev" className="cv" />
        <span className="meter sm" aria-hidden="true">
          <i style={{ width: `${String(percent)}%` }} />
        </span>
      </button>
      {open && (
        <div className="gs-b" id="goals-list">
          <Checklist tasks={shown} />
        </div>
      )}
    </div>
  );
}
