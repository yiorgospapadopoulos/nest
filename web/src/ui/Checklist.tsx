import type { TrackedTask } from "../api/types.ts";
import { Icon } from "./Icon.tsx";
import { Fireflies } from "./Fireflies.tsx";

/** An agent's steps as checkboxes: done, in progress, pending. Deleted ones are left to the caller. */
export function Checklist({ tasks, label }: { tasks: TrackedTask[]; label?: string }) {
  return (
    <ul className="ck" aria-label={label}>
      {tasks.map((task) => (
        <TaskItem key={task.id} task={task} />
      ))}
    </ul>
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
          <Fireflies />
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
