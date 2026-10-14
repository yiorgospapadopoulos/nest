import { describe, expect, it } from "vitest";
import type { HabitSchedule } from "../../api/types.ts";
import { habitRun } from "../../test/fixtures.ts";
import { outcomeText, runDuration, scheduleText, triggersText } from "./habits.ts";

describe("habit wording (B42)", () => {
  it.each<[HabitSchedule | null, string]>([
    [{ kind: "hourly", minute: 15 }, "Every hour at :15"],
    [{ kind: "hourly", minute: 5 }, "Every hour at :05"],
    [{ kind: "daily", time: "08:30" }, "Every day at 08:30"],
    [{ kind: "weekdays", time: "09:00" }, "Weekdays at 09:00"],
    [{ kind: "weekly", weekday: 0, time: "09:00" }, "Mondays at 09:00"],
    [{ kind: "weekly", weekday: 6, time: "18:00" }, "Sundays at 18:00"],
    [{ kind: "weekly", weekday: 9, time: "18:00" }, "Every week at 18:00"],
    [null, "No schedule"],
  ])("summarizes the schedule %j", (schedule, text) => {
    expect(scheduleText(schedule)).toBe(text);
  });

  it("names the triggers in words", () => {
    expect(triggersText([])).toBe("");
    expect(triggersText(["stuck"])).toBe("When a chat looks stuck");
    expect(triggersText(["failed", "ci_failed"])).toBe(
      "When a chat fails or pull request checks fail",
    );
    expect(triggersText(["stuck", "failed", "review_ready"])).toBe(
      "When a chat looks stuck, a chat fails or work is ready for review",
    );
  });

  it("names each outcome, with the reason when there is one", () => {
    expect(outcomeText(habitRun())).toBe("Reported");
    expect(outcomeText(habitRun({ outcome: "quiet" }))).toBe("Nothing to report");
    expect(outcomeText(habitRun({ outcome: "timed_out" }))).toBe("Timed out");
    expect(outcomeText(habitRun({ outcome: "skipped", reason: "usage" }))).toBe("Skipped (usage)");
  });

  it("measures a run from start to end", () => {
    expect(runDuration(habitRun())).toBe("2m 30s");
    expect(runDuration(habitRun({ ended_at: null }))).toBeNull();
    expect(runDuration(habitRun({ started_at: null }))).toBeNull();
  });
});
