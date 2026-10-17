import { describe, expect, it } from "vitest";
import { usagePeriod } from "../../test/fixtures.ts";
import {
  barHeight,
  barTip,
  chatCount,
  isoDay,
  periodRange,
  periodTitle,
  probesLine,
  projectRows,
  share,
  stepDate,
  ticks,
} from "./usageText.ts";

// Saturday 17 October 2026, mid-morning.
const today = new Date(2026, 9, 17, 10, 14);

describe("usage periods", () => {
  it("writes a local day as YYYY-MM-DD", () => {
    expect(isoDay(today)).toBe("2026-10-17");
    expect(isoDay(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
  });

  it("finds the period holding a day, weeks from Monday", () => {
    expect(periodRange("day", "2026-10-17")).toEqual({ start: "2026-10-17", end: "2026-10-17" });
    expect(periodRange("week", "2026-10-17")).toEqual({ start: "2026-10-12", end: "2026-10-18" });
    // A Sunday belongs to the week before it, and a Monday starts its own.
    expect(periodRange("week", "2026-10-18").start).toBe("2026-10-12");
    expect(periodRange("week", "2026-10-19").start).toBe("2026-10-19");
    expect(periodRange("month", "2026-02-10")).toEqual({ start: "2026-02-01", end: "2026-02-28" });
    expect(periodRange("year", "2026-10-17")).toEqual({ start: "2026-01-01", end: "2026-12-31" });
  });

  it("steps to the day before the period or after it", () => {
    expect(stepDate("day", "2026-10-01", -1)).toBe("2026-09-30");
    expect(stepDate("week", "2026-10-17", -1)).toBe("2026-10-11");
    expect(stepDate("week", "2026-10-17", 1)).toBe("2026-10-19");
    expect(stepDate("month", "2026-03-15", -1)).toBe("2026-02-28");
    expect(stepDate("year", "2026-06-01", 1)).toBe("2027-01-01");
  });

  it("titles each period as the Mac does", () => {
    expect(periodTitle("day", "2026-10-17", today)).toBe("Today");
    expect(periodTitle("day", "2026-10-16", today)).toBe("Fri 16 Oct");
    expect(periodTitle("week", "2026-10-14", today)).toBe("12 to 18 Oct");
    // Short months are the Mac's, never the browser's ("Sept").
    expect(periodTitle("week", "2026-10-01", today)).toBe("28 Sep to 4 Oct");
    expect(periodTitle("day", "2026-09-30", today)).toBe("Wed 30 Sep");
    expect(periodTitle("month", "2026-10-03", today)).toBe("October");
    expect(periodTitle("month", "2025-10-03", today)).toBe("October 2025");
    expect(periodTitle("year", "2025-10-03", today)).toBe("2025");
  });

  it("labels the axis of each period", () => {
    expect(ticks("day", "2026-10-17")).toEqual(["0", "6", "12", "18", "23"]);
    expect(ticks("week", "2026-10-17")).toEqual(["Mo", "We", "Fr", "Su"]);
    expect(ticks("month", "2026-09-17")).toEqual(["1", "8", "15", "22", "30"]);
    expect(ticks("year", "2026-09-17")).toEqual(["Jan", "Apr", "Jul", "Oct", "Dec"]);
  });
});

describe("usage numbers", () => {
  it("explains a bar by its hour, day or month", () => {
    const bar = { start: "2026-10-14T14:00:00+03:00", tokens: 3_400_000, sessions: 12 };
    expect(barTip("day", bar)).toBe("14:00: 3.4M tokens, 12 chats");
    expect(barTip("week", bar)).toBe("Wed 14 Oct: 3.4M tokens, 12 chats");
    expect(barTip("month", { ...bar, sessions: 1 })).toBe("Wed 14 Oct: 3.4M tokens, 1 chat");
    expect(barTip("year", { ...bar, tokens: 0, sessions: 0 })).toBe("October: 0 tokens, 0 chats");
    const sunday = { start: "2026-09-27T00:00:00+03:00", tokens: 5, sessions: 1 };
    expect(barTip("month", sunday)).toBe("Sun 27 Sep: 5 tokens, 1 chat");
  });

  it("sizes bars against the busiest one, with a floor for small ones", () => {
    expect(barHeight(3_650_000, 3_650_000)).toBe(64);
    expect(barHeight(1, 3_650_000)).toBe(3);
    expect(barHeight(0, 3_650_000)).toBe(1);
    expect(barHeight(0, 0)).toBe(1);
  });

  it("counts chats", () => {
    expect(chatCount(1)).toBe("1 chat");
    expect(chatCount(74)).toBe("74 chats");
  });

  it("writes shares, small ones with more digits", () => {
    expect(share(13_400_000, 15_000_000)).toBe("89%");
    expect(share(105_000, 15_000_000)).toBe("0.7%");
    expect(share(1_600, 15_000_000)).toBe("0.01%");
    expect(share(1, 15_000_000)).toBe("<0.01%");
    expect(share(0, 15_000_000)).toBe("0%");
    expect(share(0, 0)).toBe("0%");
  });

  it("keeps the top four projects and folds the rest into Others", () => {
    const rows = projectRows(usagePeriod().projects);
    expect(rows).toEqual([
      { name: "DEMO", tokens: 7_160_000 },
      { name: "CV-page", tokens: 2_210_000 },
      { name: "b59-live", tokens: 1_390_000 },
      { name: "Pixies", tokens: 1_120_000 },
      { name: "Others (2)", tokens: 1_520_000 },
    ]);
    expect(projectRows(usagePeriod().projects.slice(0, 4))).toHaveLength(4);
  });

  it("describes the usage checks, or nothing when there were none", () => {
    expect(probesLine({ count: 12, tokens: 5_000 })).toBe(
      "12 usage checks, 5k tokens, not counted above",
    );
    expect(probesLine({ count: 1, tokens: 400 })).toBe(
      "1 usage check, 400 tokens, not counted above",
    );
    expect(probesLine({ count: 0, tokens: 0 })).toBeNull();
  });
});
