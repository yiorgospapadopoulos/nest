import { useEffect, useState } from "react";
import type { Habit, HabitRun } from "../../api/types.ts";
import { activityTime } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import { Sheet } from "../../ui/Sheet.tsx";
import { outcomeText, runDuration } from "./habits.ts";

interface Props {
  habit: Habit;
  onOpenChat: (sessionId: string) => void;
  onClose: () => void;
}

/**
 * A habit's latest runs, newest first (B42): outcome, start time, duration and report
 * title, and its transcript, read only. Runs that start or end meanwhile follow live.
 */
export function HabitHistory({ habit, onOpenChat, onClose }: Props) {
  const { state, actions } = useStore();
  const [loading, setLoading] = useState(true);
  const runs = state.habitRuns[habit.id];

  useEffect(() => {
    void actions.loadHabitRuns(habit.pixie_id, habit.id).then(() => {
      setLoading(false);
    });
  }, [actions, habit.pixie_id, habit.id]);

  return (
    <Sheet title={`${habit.name} history`} full onClose={onClose}>
      {runs === undefined && loading && <p className="hint">Loading...</p>}
      {runs === undefined && !loading && <p className="hint">The history could not be loaded.</p>}
      {runs?.length === 0 && <p className="hint">No runs yet</p>}
      {runs !== undefined && runs.length > 0 && (
        <ul className="lgrp gl pxact">
          {runs.map((run) => (
            <RunRow key={run.id} run={run} onOpenChat={onOpenChat} />
          ))}
        </ul>
      )}
    </Sheet>
  );
}

function RunRow({ run, onOpenChat }: { run: HabitRun; onOpenChat: (sessionId: string) => void }) {
  const duration = runDuration(run);
  const chat = run.session_id;
  return (
    <li className="srow">
      <span className="pxdt">
        <span className="pxacth">
          <b>{outcomeText(run)}</b>
          <small>
            {run.started_at !== null && activityTime(run.started_at, new Date())}
            {duration !== null && `, ${duration}`}
          </small>
        </span>
        {run.report_title !== null && <span className="pxact-t">{run.report_title}</span>}
        {chat !== null && (
          <button
            className="pxlnk"
            onClick={() => {
              onOpenChat(chat);
            }}
          >
            Open transcript
          </button>
        )}
      </span>
    </li>
  );
}
