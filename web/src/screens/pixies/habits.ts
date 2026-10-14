import type {
  HabitOutcome,
  HabitRun,
  HabitSchedule,
  HabitTrigger,
  ReportSeverity,
} from "../../api/types.ts";
import { elapsed } from "../../transcript/activity.ts";

// Monday is 0, as the daemon counts.
export const WEEKDAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

export type ScheduleKind = HabitSchedule["kind"];

export const SCHEDULE_KINDS: Record<ScheduleKind, string> = {
  hourly: "Every hour",
  daily: "Every day",
  weekdays: "Weekdays",
  weekly: "Every week",
};

// What happened, as the end of "When ...", in the order the editor lists them.
export const TRIGGERS: Record<HabitTrigger, string> = {
  stuck: "a chat looks stuck",
  failed: "a chat fails",
  review_ready: "work is ready for review",
  ci_failed: "pull request checks fail",
};

const OUTCOMES: Record<HabitOutcome, string> = {
  queued: "Queued",
  running: "Running",
  reported: "Reported",
  quiet: "Nothing to report",
  failed: "Failed",
  stalled: "Stalled",
  timed_out: "Timed out",
  skipped: "Skipped",
};

export const SEVERITIES: Record<ReportSeverity, string> = {
  info: "Info",
  warn: "Warning",
  action: "Needs action",
};

/** "Weekdays at 09:00", "Every hour at :15", or "No schedule". */
export function scheduleText(schedule: HabitSchedule | null): string {
  if (schedule === null) return "No schedule";
  switch (schedule.kind) {
    case "hourly":
      return `Every hour at :${String(schedule.minute).padStart(2, "0")}`;
    case "daily":
      return `Every day at ${schedule.time}`;
    case "weekdays":
      return `Weekdays at ${schedule.time}`;
    case "weekly": {
      const day = WEEKDAYS[schedule.weekday];
      return day === undefined ? `Every week at ${schedule.time}` : `${day}s at ${schedule.time}`;
    }
  }
}

/** "When a chat looks stuck or a chat fails"; empty without triggers. */
export function triggersText(triggers: HabitTrigger[]): string {
  const words = triggers.map((t) => TRIGGERS[t]);
  const last = words.pop();
  if (last === undefined) return "";
  return `When ${words.length > 0 ? `${words.join(", ")} or ` : ""}${last}`;
}

/** "Reported", or "Skipped (usage)" with the reason the Mac gave. */
export function outcomeText(run: HabitRun): string {
  const word = OUTCOMES[run.outcome];
  return run.reason === null ? word : `${word} (${run.reason})`;
}

/** How long a run took, once it ended. */
export function runDuration(run: HabitRun): string | null {
  if (run.started_at === null || run.ended_at === null) return null;
  return elapsed(new Date(run.ended_at).getTime() - new Date(run.started_at).getTime());
}
