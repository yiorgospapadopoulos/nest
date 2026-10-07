import { useState } from "react";
import type { TrackedTask } from "../../api/types.ts";
import { Icon } from "../../ui/Icon.tsx";

/** The agent's task list: the current step with progress, expanding to the checklist. */
export function GoalsStrip({ tasks }: { tasks: TrackedTask[] }) {
  const [open, setOpen] = useState(false);
  const shown = tasks.filter((t) => t.status !== "deleted");
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
          <ul className="ck">
            {shown.map((task) => (
              <TaskItem key={task.id} task={task} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function TaskItem({ task }: { task: TrackedTask }) {
  if (task.status === "completed") {
    return (
      <li className="done">
        <span className="cki ok" aria-hidden="true">
          <Icon name="check" />
        </span>
        <span className="x">
          <span className="sr">done: </span>
          {task.subject}
        </span>
      </li>
    );
  }
  if (task.status === "in_progress") {
    return (
      <li className="act">
        <span className="cki" aria-hidden="true">
          <span className="spin" />
        </span>
        <span className="x">
          <span className="sr">in progress: </span>
          {task.active_form ?? task.subject}
        </span>
      </li>
    );
  }
  return (
    <li>
      <span className="cki pn" aria-hidden="true" />
      <span className="x">
        <span className="sr">pending: </span>
        {task.subject}
      </span>
    </li>
  );
}
