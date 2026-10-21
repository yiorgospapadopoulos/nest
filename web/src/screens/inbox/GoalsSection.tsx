import { useEffect, type CSSProperties } from "react";
import type { TrackedTask } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { goalEntries } from "../../store/selectors.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { FoldRow } from "./FoldRow.tsx";

interface Props {
  project: string;
  onOpenChat: (sessionId: string) => void;
}

/**
 * Under Needs you, as the Mac's right panel (B47, B102 item 11): each chat at work or with
 * steps showing, as a row with its progress and a thin bar, its steps open beneath, kept
 * current by the live events.
 */
export function GoalsSection({ project, onOpenChat }: Props) {
  const { state, actions } = useStore();
  useEffect(() => {
    void actions.loadGoals(project);
  }, [actions, project]);
  const entries = goalEntries(state, project);
  if (entries.length === 0) return null;

  return (
    <section className="goals" aria-label="Goals">
      <h2 className="lbl">
        Goals
        <span className="c">{entries.length}</span>
      </h2>
      {entries.map(({ session, status, tasks }) => {
        const done = tasks.filter((t) => t.status === "completed").length;
        const progress =
          tasks.length === 0 ? "No plan yet" : `${String(done)} of ${String(tasks.length)}`;
        return (
          <FoldRow
            key={session.id}
            label={`${session.title}: ${progress}, ${status.label}`}
            tone={status.tone}
            name={session.title}
            onOpen={() => {
              onOpenChat(session.id);
            }}
            line={
              <>
                {progress}
                {tasks.length > 0 && (
                  <span
                    className="gbar"
                    aria-hidden="true"
                    style={
                      {
                        "--done": `${String(Math.round((done / tasks.length) * 100))}%`,
                      } as CSSProperties
                    }
                  />
                )}
              </>
            }
            openByDefault
          >
            {tasks.length > 0 && <Steps tasks={tasks} label={`Steps of ${session.title}`} />}
          </FoldRow>
        );
      })}
    </section>
  );
}

/** A goal's numbered steps: done, in progress with what it is doing, or still to do. */
function Steps({ tasks, label }: { tasks: TrackedTask[]; label: string }) {
  return (
    <ol className="steps" aria-label={label}>
      {tasks.map((task, index) => {
        const state =
          task.status === "completed" ? "done" : task.status === "in_progress" ? "cur" : "todo";
        return (
          <li key={task.id} className={state}>
            <span className="smark" aria-hidden="true">
              {state === "done" ? (
                <Icon name="check" />
              ) : state === "cur" ? (
                <Fireflies size={9} />
              ) : (
                <span className="sopen" />
              )}
            </span>
            <span className="snum" aria-hidden="true">
              {index + 1}
            </span>
            <span className="stext">
              <span className="sr">{`${state === "done" ? "done" : state === "cur" ? "in progress" : "pending"}: `}</span>
              {task.subject}
              {state === "cur" && task.active_form !== null && (
                <span className="sdoing">{task.active_form}</span>
              )}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
