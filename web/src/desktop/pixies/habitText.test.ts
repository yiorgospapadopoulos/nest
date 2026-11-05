import { describe, expect, it } from "vitest";
import { habit, habitRun } from "../../test/fixtures.ts";
import {
  clockTime,
  draftOf,
  habitSummary,
  lastRunText,
  newDraft,
  nextRunText,
  parseClock,
  problemOf,
  canSave,
  createBody,
  runDuration,
  scheduleOf,
  scheduleText,
  startedText,
  triggersText,
  updateBody,
  REPEATS,
} from "./habitText.ts";

// Ported from NestKitTests' PixieHabitsTests (B42), in UTC as there.
const UTC = "UTC";
const now = new Date("2026-10-14T12:00:00Z");
const run = habitRun({
  due_at: "2026-10-14T09:00:00Z",
  started_at: "2026-10-14T09:00:00Z",
  ended_at: "2026-10-14T09:02:05Z",
});

describe("habit words", () => {
  it("reads a time as today's clock, or the day and the clock", () => {
    expect(clockTime("2026-10-14T09:05:00Z", now, UTC)).toBe("09:05");
    expect(clockTime("2026-10-12T17:30:00Z", now, UTC)).toBe("12 Oct 17:30");
  });

  it("reads schedules and triggers plainly", () => {
    expect(scheduleText({ kind: "hourly", minute: 5 })).toBe("Every hour at :05");
    expect(scheduleText({ kind: "daily", time: "07:30" })).toBe("Every day at 07:30");
    expect(scheduleText({ kind: "weekdays", time: "09:00" })).toBe("Weekdays at 09:00");
    expect(scheduleText({ kind: "weekly", weekday: 0, time: "08:00" })).toBe("Mondays at 08:00");
    expect(scheduleText({ kind: "weekly", weekday: 9, time: "18:00" })).toBe("Weekly at 18:00");
    expect(triggersText([])).toBeNull();
    expect(triggersText(["stuck", "failed"])).toBe("When a chat is stuck or fails");
    expect(triggersText(["stuck", "failed", "review_ready", "ci_failed"])).toBe(
      "When a chat is stuck, fails, is ready for review or fails CI",
    );
    expect(habitSummary(habit({ triggers: ["stuck", "ci_failed"] }))).toBe(
      "Weekdays at 09:00 · When a chat is stuck or fails CI",
    );
    expect(habitSummary(habit({ schedule: null, triggers: [] }))).toBe("");
  });

  it("reads the last and next run plainly", () => {
    expect(lastRunText(null, now, UTC)).toBe("Not run yet");
    expect(lastRunText(run, now, UTC)).toBe("Reported 09:02");
    expect(lastRunText({ ...run, outcome: "running", ended_at: null }, now, UTC)).toBe(
      "Running since 09:00",
    );
    expect(lastRunText({ ...run, outcome: "queued", started_at: null }, now, UTC)).toBe("Queued");
    expect(
      lastRunText(
        { ...run, outcome: "skipped", started_at: null, ended_at: null, reason: "late" },
        now,
        UTC,
      ),
    ).toBe("Skipped 09:00 (late)");
    expect(
      lastRunText(
        { ...run, outcome: "quiet", started_at: null, ended_at: null, due_at: null },
        now,
        UTC,
      ),
    ).toBe("Quiet");
    expect(nextRunText(habit({ next_due_at: "2026-10-15T09:00:00Z" }), now, UTC)).toBe(
      "Next 15 Oct 09:00",
    );
    expect(nextRunText(habit({ enabled: false }), now, UTC)).toBe("Paused");
    expect(nextRunText(habit({ next_due_at: null }), now, UTC)).toBe("Runs on events");
  });

  it("reads history rows plainly", () => {
    expect(startedText(run, now, UTC)).toBe("09:00");
    expect(runDuration(run, now)).toBe("2m 5s");
    expect(runDuration({ ...run, outcome: "running", ended_at: null }, now)).toBe("3h");
    const skipped = { ...run, outcome: "skipped" as const, started_at: null, ended_at: null };
    expect(startedText(skipped, now, UTC)).toBe("Due 09:00");
    expect(runDuration(skipped, now)).toBeNull();
    expect(startedText({ ...skipped, due_at: null }, now, UTC)).toBe("");
  });
});

describe("the habit editor's draft", () => {
  it("starts daily at nine", () => {
    const draft = newDraft();
    expect(scheduleOf(draft)).toEqual({ kind: "daily", time: "09:00" });
    expect(draft.maxMinutes).toBe(20);
    expect(canSave(draft)).toBe(false);
    expect(REPEATS.map((r) => r.label)).toEqual([
      "No schedule",
      "Every hour",
      "Every day",
      "Weekdays",
      "Weekly",
    ]);
  });

  it("reads a typed time only when it is a 24 hour one", () => {
    expect(parseClock("9:05")).toEqual({ hour: 9, minute: 5 });
    expect(parseClock(" 17:45 ")).toEqual({ hour: 17, minute: 45 });
    expect(parseClock("24:00")).toBeNull();
    expect(parseClock("9:60")).toBeNull();
    expect(parseClock("9 AM")).toBeNull();
  });

  it("builds each schedule", () => {
    const draft = { ...newDraft(), hour: 7, minute: 5, hourlyMinute: 45, weekday: 2 };
    expect(scheduleOf({ ...draft, repeats: "hourly" })).toEqual({ kind: "hourly", minute: 45 });
    expect(scheduleOf({ ...draft, repeats: "weekdays" })).toEqual({
      kind: "weekdays",
      time: "07:05",
    });
    expect(scheduleOf({ ...draft, repeats: "weekly" })).toEqual({
      kind: "weekly",
      weekday: 2,
      time: "07:05",
    });
    expect(scheduleOf({ ...draft, repeats: "never" })).toBeNull();
  });

  it("says what is missing, as the daemon would refuse it", () => {
    const draft = { ...newDraft(), name: "  ", prompt: "Look" };
    // An empty name only keeps Save off; it has no message (B85).
    expect(problemOf(draft)).toBeNull();
    expect(canSave(draft)).toBe(false);
    expect(problemOf({ ...draft, prompt: "" })).toBe("Say what it should check");
    expect(problemOf({ ...draft, name: "a".repeat(61), prompt: "" })).toBe(
      "A name has at most 60 characters",
    );
    expect(problemOf({ ...draft, name: "Check", prompt: "b".repeat(4001) })).toBe(
      "The instructions have at most 4000 characters",
    );
    const ready = { ...draft, name: "Check" };
    expect(canSave(ready)).toBe(true);
    expect(problemOf({ ...ready, repeats: "never" })).toBe(
      "Choose a schedule or at least one trigger",
    );
    expect(problemOf({ ...ready, repeats: "never", triggers: ["failed"] })).toBeNull();
  });

  it("comes from a habit and saves only what changed", () => {
    const saved = habit({
      name: "Morning check",
      prompt: "Look at failing PRs",
      schedule: { kind: "weekly", weekday: 3, time: "17:45" },
      triggers: ["failed"],
    });
    const draft = draftOf(saved);
    expect(draft).toMatchObject({ repeats: "weekly", weekday: 3, hour: 17, minute: 45 });
    expect(updateBody(draft, saved)).toEqual({});
    const changed = {
      ...draft,
      name: " Evening check ",
      prompt: "New",
      triggers: ["failed", "stuck"] as const,
      maxMinutes: 30,
      repeats: "hourly" as const,
      hourlyMinute: 10,
    };
    expect(updateBody({ ...changed, triggers: [...changed.triggers] }, saved)).toEqual({
      name: "Evening check",
      prompt: "New",
      schedule: { kind: "hourly", minute: 10 },
      triggers: ["stuck", "failed"],
      max_minutes: 30,
    });
    expect(updateBody({ ...draft, autopilot: true }, saved)).toEqual({ autopilot: true });
    // No schedule any more clears it.
    expect(updateBody({ ...draft, repeats: "never" }, saved)).toEqual({ schedule: null });
    expect(draftOf(habit({ schedule: null })).repeats).toBe("never");
    expect(draftOf(habit({ schedule: { kind: "daily", time: "late" } })).hour).toBe(9);
  });

  it("makes the create body with trimmed text and the triggers in order", () => {
    const draft = { ...newDraft(), name: " Check ", prompt: " Look \n" };
    expect(createBody({ ...draft, triggers: ["ci_failed", "stuck"] })).toEqual({
      name: "Check",
      prompt: "Look",
      schedule: { kind: "daily", time: "09:00" },
      triggers: ["stuck", "ci_failed"],
      max_minutes: 20,
      autopilot: false,
    });
  });
});
