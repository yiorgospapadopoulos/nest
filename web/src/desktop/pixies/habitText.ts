// The words of a pixie's Habits page, its history and the habit editor (B42), and the
// editor's form as values, as NestKit's HabitPresentation.
import type {
  Habit,
  HabitBody,
  HabitOutcome,
  HabitRun,
  HabitSchedule,
  HabitTrigger,
  UpdateHabitBody,
} from "../../api/types.ts";
import type { Tone } from "../../store/selectors.ts";

export const EMPTY_LIST =
  "No habits yet. A habit runs on a schedule or when chats need attention, and reports what it finds.";
export const EMPTY_HISTORY = "No runs yet.";

// Monday first, as the daemon numbers them.
export const WEEKDAY_NAMES = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

// The editor's checkboxes, in the order it lists them, and what follows "When a chat".
export const TRIGGERS: { value: HabitTrigger; label: string; phrase: string }[] = [
  { value: "stuck", label: "A chat is stuck", phrase: "is stuck" },
  { value: "failed", label: "A chat fails", phrase: "fails" },
  { value: "review_ready", label: "A chat is ready for review", phrase: "is ready for review" },
  { value: "ci_failed", label: "A pull request's checks fail", phrase: "fails CI" },
];

export const OUTCOMES: Record<HabitOutcome, { label: string; tone: Tone }> = {
  queued: { label: "Queued", tone: "run" },
  running: { label: "Running", tone: "run" },
  reported: { label: "Reported", tone: "rev" },
  quiet: { label: "Quiet", tone: "done" },
  failed: { label: "Failed", tone: "fail" },
  stalled: { label: "Stalled", tone: "wait" },
  timed_out: { label: "Timed out", tone: "fail" },
  skipped: { label: "Skipped", tone: "int" },
};

const isActive = (outcome: HabitOutcome) => outcome === "queued" || outcome === "running";

const two = (n: number) => String(n).padStart(2, "0");

/** "09:05" today, "12 Oct 17:30" on another day, in `timeZone` (the user's by default). */
export function clockTime(iso: string, now: Date, timeZone?: string): string {
  const parts = (date: Date) =>
    Object.fromEntries(
      new Intl.DateTimeFormat("en-GB", {
        timeZone,
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      })
        .formatToParts(date)
        .map((part) => [part.type, part.value]),
    ) as Record<string, string>;
  const at = parts(new Date(iso));
  const today = parts(now);
  const clock = `${at.hour ?? ""}:${at.minute ?? ""}`;
  const sameDay = at.year === today.year && at.month === today.month && at.day === today.day;
  return sameDay ? clock : `${at.day ?? ""} ${at.month ?? ""} ${clock}`;
}

/** "Every hour at :15", "Every day at 07:30", "Weekdays at 09:00", "Mondays at 08:00". */
export function scheduleText(schedule: HabitSchedule): string {
  switch (schedule.kind) {
    case "hourly":
      return `Every hour at :${two(schedule.minute)}`;
    case "daily":
      return `Every day at ${schedule.time}`;
    case "weekdays":
      return `Weekdays at ${schedule.time}`;
    case "weekly": {
      const day = WEEKDAY_NAMES[schedule.weekday];
      return day === undefined ? `Weekly at ${schedule.time}` : `${day}s at ${schedule.time}`;
    }
  }
}

/** "When a chat is stuck, fails or fails CI"; null without triggers. */
export function triggersText(triggers: HabitTrigger[]): string | null {
  const phrases = TRIGGERS.filter((t) => triggers.includes(t.value)).map((t) => t.phrase);
  const last = phrases.pop();
  if (last === undefined) return null;
  return `When a chat ${phrases.length > 0 ? `${phrases.join(", ")} or ` : ""}${last}`;
}

/** "Weekdays at 09:00 · When a chat is stuck". */
export function habitSummary(habit: Pick<Habit, "schedule" | "triggers">): string {
  return [
    habit.schedule === null ? null : scheduleText(habit.schedule),
    triggersText(habit.triggers),
  ]
    .filter((part) => part !== null)
    .join(" · ");
}

/** "Reported 09:02", "Running since 09:00", "Skipped 09:00 (late)", "Queued" or "Not run yet". */
export function lastRunText(run: HabitRun | null, now: Date, timeZone?: string): string {
  if (run === null) return "Not run yet";
  const label = OUTCOMES[run.outcome].label;
  if (run.outcome === "queued") return label;
  if (run.outcome === "running") {
    return `Running since ${run.started_at === null ? "now" : clockTime(run.started_at, now, timeZone)}`;
  }
  const at = run.ended_at ?? run.started_at ?? run.due_at;
  const when = at === null ? "" : ` ${clockTime(at, now, timeZone)}`;
  const why = run.reason === null ? "" : ` (${run.reason})`;
  return label + when + why;
}

/** "Next 09:00", "Paused", or "Runs on events" for a habit with no time due. */
export function nextRunText(habit: Habit, now: Date, timeZone?: string): string {
  if (!habit.enabled) return "Paused";
  if (habit.next_due_at === null) return "Runs on events";
  return `Next ${clockTime(habit.next_due_at, now, timeZone)}`;
}

/** A history row's time: when it started, else "Due 09:00" for one that never did. */
export function startedText(run: HabitRun, now: Date, timeZone?: string): string {
  if (run.started_at !== null) return clockTime(run.started_at, now, timeZone);
  return run.due_at === null ? "" : `Due ${clockTime(run.due_at, now, timeZone)}`;
}

/** A run time with seconds while short, "8s", "3m 4s", then "1h 12m", as Elapsed.duration. */
export function durationText(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < 60) return `${String(whole)}s`;
  if (whole < 3600) {
    const rest = whole % 60;
    return `${String(Math.floor(whole / 60))}m${rest > 0 ? ` ${String(rest)}s` : ""}`;
  }
  const minutes = Math.floor(whole / 60);
  if (minutes < 24 * 60) {
    const rest = minutes % 60;
    return `${String(Math.floor(minutes / 60))}h${rest > 0 ? ` ${String(rest)}m` : ""}`;
  }
  return `${String(Math.floor(minutes / (24 * 60)))}d`;
}

/** How long it ran, or runs so far; null for one that never started. */
export function runDuration(run: HabitRun, now: Date): string | null {
  if (run.started_at === null) return null;
  const end = run.ended_at ?? (isActive(run.outcome) ? now.toISOString() : null);
  if (end === null) return null;
  return durationText((new Date(end).getTime() - new Date(run.started_at).getTime()) / 1000);
}

// The editor's form.

export type Repeat = "never" | "hourly" | "daily" | "weekdays" | "weekly";

export const REPEATS: { value: Repeat; label: string }[] = [
  { value: "never", label: "No schedule" },
  { value: "hourly", label: "Every hour" },
  { value: "daily", label: "Every day" },
  { value: "weekdays", label: "Weekdays" },
  { value: "weekly", label: "Weekly" },
];

export const MAX_MINUTES = { min: 1, max: 120 };

export interface HabitDraft {
  name: string;
  prompt: string;
  repeats: Repeat;
  // The minute of an hourly habit.
  hourlyMinute: number;
  hour: number;
  minute: number;
  weekday: number;
  triggers: HabitTrigger[];
  maxMinutes: number;
}

export function newDraft(): HabitDraft {
  return {
    name: "",
    prompt: "",
    repeats: "daily",
    hourlyMinute: 0,
    hour: 9,
    minute: 0,
    weekday: 0,
    triggers: [],
    maxMinutes: 20,
  };
}

/** The draft of a saved habit, for Edit. */
export function draftOf(habit: Habit): HabitDraft {
  const draft: HabitDraft = {
    ...newDraft(),
    name: habit.name,
    prompt: habit.prompt,
    triggers: [...habit.triggers],
    maxMinutes: habit.max_minutes,
  };
  const schedule = habit.schedule;
  if (schedule === null) return { ...draft, repeats: "never" };
  draft.repeats = schedule.kind;
  if (schedule.kind === "hourly") draft.hourlyMinute = schedule.minute;
  else {
    if (schedule.kind === "weekly") draft.weekday = schedule.weekday;
    const [hour, minute] = schedule.time.split(":").map(Number);
    if (
      hour !== undefined &&
      minute !== undefined &&
      Number.isInteger(hour) &&
      Number.isInteger(minute) &&
      hour >= 0 &&
      hour < 24 &&
      minute >= 0 &&
      minute < 60
    ) {
      draft.hour = hour;
      draft.minute = minute;
    }
  }
  return draft;
}

/** "HH:MM". */
export function clockText(hour: number, minute: number): string {
  return `${two(hour)}:${two(minute)}`;
}

export function timeOf(draft: HabitDraft): string {
  return clockText(draft.hour, draft.minute);
}

/** A typed 24 hour time, "9:05" or "09:05"; null when it is not one. */
export function parseClock(text: string): { hour: number; minute: number } | null {
  const match = /^\s*(\d{1,2}):(\d{2})\s*$/.exec(text);
  if (match === null) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  return hour < 24 && minute < 60 ? { hour, minute } : null;
}

export function scheduleOf(draft: HabitDraft): HabitSchedule | null {
  const time = timeOf(draft);
  switch (draft.repeats) {
    case "never":
      return null;
    case "hourly":
      return { kind: "hourly", minute: draft.hourlyMinute };
    case "daily":
      return { kind: "daily", time };
    case "weekdays":
      return { kind: "weekdays", time };
    case "weekly":
      return { kind: "weekly", weekday: draft.weekday, time };
  }
}

const ordered = (triggers: HabitTrigger[]) =>
  TRIGGERS.map((t) => t.value).filter((t) => triggers.includes(t));

/**
 * Why it cannot be saved yet, as the daemon would refuse it. An empty name only keeps
 * Save off: it goes without saying (B85).
 */
export function problemOf(draft: HabitDraft): string | null {
  const name = draft.name.trim();
  const prompt = draft.prompt.trim();
  if (name.length > 60) return "A name has at most 60 characters";
  if (prompt === "") return "Say what it should check";
  if (prompt.length > 4000) return "The instructions have at most 4000 characters";
  if (scheduleOf(draft) === null && draft.triggers.length === 0) {
    return "Choose a schedule or at least one trigger";
  }
  return null;
}

export function canSave(draft: HabitDraft): boolean {
  return draft.name.trim() !== "" && problemOf(draft) === null;
}

export function createBody(draft: HabitDraft): HabitBody {
  return {
    name: draft.name.trim(),
    prompt: draft.prompt.trim(),
    schedule: scheduleOf(draft),
    triggers: ordered(draft.triggers),
    max_minutes: draft.maxMinutes,
  };
}

function sameSchedule(a: HabitSchedule | null, b: HabitSchedule | null): boolean {
  if (a === null || b === null) return a === b;
  return scheduleText(a) === scheduleText(b) && a.kind === b.kind;
}

/** Only what changed from the habit; no schedule any more sends null, which clears it. */
export function updateBody(draft: HabitDraft, habit: Habit): UpdateHabitBody {
  const body: UpdateHabitBody = {};
  const name = draft.name.trim();
  const prompt = draft.prompt.trim();
  const schedule = scheduleOf(draft);
  const triggers = ordered(draft.triggers);
  if (name !== habit.name) body.name = name;
  if (prompt !== habit.prompt) body.prompt = prompt;
  if (!sameSchedule(schedule, habit.schedule)) body.schedule = schedule;
  if (triggers.join(" ") !== habit.triggers.join(" ")) body.triggers = triggers;
  if (draft.maxMinutes !== habit.max_minutes) body.max_minutes = draft.maxMinutes;
  return body;
}
