// What both clients choose and show for Autopilot (B120). A new chat's choice goes with its
// request; an open chat's goes to the daemon at once and comes back on the session.
import { useState } from "react";
import type {
  AutopilotBudget,
  AutopilotEnd,
  AutopilotRun,
  CreateSessionBody,
  Session,
  TrackedTask,
  WeeklyCap,
} from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { elapsed } from "../../transcript/activity.ts";
import type { Option } from "./options.ts";

export const ENDED: Record<AutopilotEnd, string> = {
  done: "Finished",
  time: "Time ran out",
  weekly_cap: "Weekly cap reached",
  stuck: "Got stuck",
  errors: "Kept failing",
  stopped: "Stopped",
  off: "Turned off",
};

export const DECIDED = "Decided while you were away";

export type StopAfter = "done" | "time";

export const STOP_AFTER: Option<StopAfter>[] = [
  { value: "done", label: "Done only" },
  { value: "time", label: "Time" },
];

// In minutes, as strings for the segmented controls.
export const HOURS: Option<string>[] = [1, 2, 4, 8].map((hours) => ({
  value: String(hours * 60),
  label: `${String(hours)} h`,
}));

const FIRST_TIME = 60;
const NO_CAP = "off";
const CAPS: WeeklyCap[] = [50, 60, 70, 80, 90];

export const WEEKLY_CAPS: Option<string>[] = [
  { value: NO_CAP, label: "Off" },
  ...CAPS.map((cap) => ({ value: String(cap), label: `${String(cap)}%` })),
];

const UNTIL_DONE: AutopilotBudget = { stop_after_minutes: null, weekly_cap: null };

// The daemon counts `until` from the run's start, also for a budget given later.
function budgetOf(run: AutopilotRun): AutopilotBudget {
  return {
    stop_after_minutes:
      run.until === null
        ? null
        : Math.round((Date.parse(run.until) - Date.parse(run.started_at)) / 60_000),
    weekly_cap: run.weekly_cap,
  };
}

export interface AutopilotControl {
  on: boolean;
  stopAfter: StopAfter;
  // An option of HOURS; another value when another client chose a time it does not list.
  minutes: string;
  // An option of WEEKLY_CAPS.
  cap: string;
  setOn: (on: boolean) => void;
  setStopAfter: (stopAfter: StopAfter) => void;
  setMinutes: (minutes: string) => void;
  setCap: (cap: string) => void;
  // What a new chat's request says.
  create: Pick<CreateSessionBody, "autopilot">;
}

interface Choice extends AutopilotBudget {
  // The chat it was made in, as a composer stays while the user moves between chats.
  chat: string | null;
  on: boolean;
}

/** Autopilot for the open chat, or with no chat for the new chat being written. */
export function useAutopilot(session: Session | undefined): AutopilotControl {
  const { actions } = useStore();
  const chat = session?.id ?? null;
  const [choice, setChoice] = useState<Choice>({ chat, on: false, ...UNTIL_DONE });
  const chosen = choice.chat === chat ? choice : { chat, on: false, ...UNTIL_DONE };
  const run = session?.autopilot;
  const on = run != null || (session === undefined && chosen.on);
  const budget = run == null ? chosen : budgetOf(run);
  const { stop_after_minutes: minutes, weekly_cap: cap } = budget;

  const change = (next: { on: boolean } & AutopilotBudget) => {
    setChoice({ chat, ...next });
    if (session === undefined) return;
    if (next.on) void actions.setAutopilot(session.id, next);
    else if (run != null) void actions.setAutopilot(session.id, { on: false });
  };
  const setBudget = (next: Partial<AutopilotBudget>) => {
    change({ on, stop_after_minutes: minutes, weekly_cap: cap, ...next });
  };

  return {
    on,
    stopAfter: minutes === null ? "done" : "time",
    minutes: String(minutes),
    cap: cap === null ? NO_CAP : String(cap),
    setOn: (next) => {
      change({ on: next, stop_after_minutes: minutes, weekly_cap: cap });
    },
    setStopAfter: (stopAfter) => {
      setBudget({ stop_after_minutes: stopAfter === "done" ? null : (minutes ?? FIRST_TIME) });
    },
    setMinutes: (value) => {
      setBudget({ stop_after_minutes: Number(value) });
    },
    setCap: (value) => {
      setBudget({ weekly_cap: value === NO_CAP ? null : (Number(value) as WeeklyCap) });
    },
    create: on ? { autopilot: { on, stop_after_minutes: minutes, weekly_cap: cap } } : {},
  };
}

/** "Step 3 of 5: Writing the first tests"; null with no step left in the chat's task list. */
export function stepLine(tasks: readonly TrackedTask[]): string | null {
  const shown = tasks.filter((task) => task.status !== "deleted");
  const current =
    shown.find((task) => task.status === "in_progress") ??
    shown.find((task) => task.status === "pending");
  if (current === undefined) return null;
  const step = `Step ${String(shown.indexOf(current) + 1)} of ${String(shown.length)}`;
  return `${step}: ${current.active_form ?? current.subject}`;
}

/** "1h 12m left · 3 decisions" on the running bar. */
export function runLine(run: AutopilotRun, now: number): string {
  const time =
    run.until === null
      ? `${elapsed(now - Date.parse(run.started_at))} running`
      : `${elapsed(Date.parse(run.until) - now)} left`;
  const count = run.decisions.length;
  if (count === 0) return time;
  return `${time} · ${String(count)} ${count === 1 ? "decision" : "decisions"}`;
}
