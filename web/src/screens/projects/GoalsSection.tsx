import { useEffect } from "react";
import { useStore } from "../../store/context.ts";
import { goalEntries } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Checklist } from "../../ui/Checklist.tsx";
import { Icon } from "../../ui/Icon.tsx";

interface Props {
  project: string;
  onOpenChat: (sessionId: string) => void;
}

/**
 * At the top of a project's chats (B47): each chat at work or with steps showing, its
 * title opening it and its steps beneath, kept current by the live events.
 */
export function GoalsSection({ project, onOpenChat }: Props) {
  const { state, actions } = useStore();
  useEffect(() => {
    void actions.loadGoals(project);
  }, [actions, project]);
  const entries = goalEntries(state, project);
  if (entries.length === 0) return null;

  return (
    <section aria-labelledby="goals-h">
      <h2 className="pg-h" id="goals-h">
        <Icon name="list" />
        Goals
      </h2>
      <div className="lgrp gl goals">
        {entries.map(({ session, status, tasks }) => {
          const done = tasks.filter((t) => t.status === "completed").length;
          const progress =
            tasks.length === 0 ? "no plan yet" : `${String(done)} of ${String(tasks.length)} done`;
          return (
            <div className="goal" key={session.id}>
              <h3>
                <button
                  className="gs-h"
                  aria-label={`${session.title}: ${progress}, ${status.label}`}
                  onClick={() => {
                    onOpenChat(session.id);
                  }}
                >
                  <Dot tone={status.tone} />
                  <span className="gs-t">{session.title}</span>
                  <span className="gs-n">
                    {tasks.length > 0 && `${String(done)} of ${String(tasks.length)}`}
                  </span>
                  <Icon name="chevr" className="chv" />
                </button>
              </h3>
              {tasks.length === 0 ? (
                <p className="goal-none">No plan yet</p>
              ) : (
                <div className="gs-b">
                  <Checklist tasks={tasks} label={`Steps of ${session.title}`} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
