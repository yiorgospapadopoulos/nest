import { describe, expect, it } from "vitest";
import { activityTime, ago, initials, percent, prLabel, resetLabel, tokens } from "./format.ts";

const now = new Date("2026-10-06T12:00:00Z");

describe("ago", () => {
  it.each([
    ["2026-10-06T11:59:30Z", "now"],
    ["2026-10-06T11:55:00Z", "5m"],
    ["2026-10-06T10:00:00Z", "2h"],
    ["2026-10-06T09:55:00Z", "2h 5m"],
    ["2026-10-03T12:00:00Z", "3d"],
  ])("%s reads %s", (iso, expected) => {
    expect(ago(iso, now)).toBe(expected);
  });
});

describe("tokens", () => {
  it.each([
    [950, "950"],
    [12_400, "12k"],
    [1_400_000, "1.4M"],
    [3_000_000, "3M"],
  ])("%i reads %s", (n, expected) => {
    expect(tokens(n)).toBe(expected);
  });
});

describe("percent", () => {
  it("clamps and rounds a fraction", () => {
    expect(percent(0.304)).toBe(30);
    expect(percent(-1)).toBe(0);
    expect(percent(2)).toBe(100);
  });
});

describe("resetLabel", () => {
  it("shows the time today and the weekday otherwise", () => {
    const today = new Date(now);
    today.setHours(18, 30, 0, 0);
    const later = new Date(now);
    later.setDate(later.getDate() + 6);
    later.setHours(9, 0, 0, 0);

    expect(resetLabel(today.toISOString(), now)).toBe("Resets 18:30");
    expect(resetLabel(later.toISOString(), now)).toMatch(/^Resets \w{3} 09:00$/);
    expect(resetLabel(null, now)).toBe("Reset time unknown");
  });
});

describe("initials", () => {
  it("takes the first letters of the first two words", () => {
    expect(initials("todo-ui")).toBe("TU");
    expect(initials("nest")).toBe("N");
    expect(initials("--")).toBe("?");
  });
});

describe("prLabel", () => {
  it("takes the number from a pull request URL", () => {
    expect(prLabel("https://github.com/me/repo/pull/42")).toBe("#42");
    expect(prLabel("https://example.com/merge-requests/3")).toBe("PR");
  });
});

describe("activityTime", () => {
  it("shows the time today and the day before that", () => {
    const at = new Date(2026, 9, 14, 18, 30);
    expect(activityTime(at.toISOString(), new Date(2026, 9, 14, 21, 0))).toBe("18:30");
    expect(activityTime(at.toISOString(), new Date(2026, 9, 15, 9, 0))).toBe("14 Oct 18:30");
  });
});
