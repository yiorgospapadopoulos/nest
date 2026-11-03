// Ported from NestKitTests' StartChatTests (the usage chip) and EngineUsageTests (B91, B98).
import { describe, expect, it } from "vitest";
import type { AccountWindow, EngineAccount } from "../../../api/types.ts";
import { NO_METER_CHOICE } from "../../../store/usageMeter.ts";
import { duration, meterLines, usageChip } from "./usage.ts";

const noon = new Date("2026-10-20T12:00:00Z");
const later = (ms: number) => new Date(noon.getTime() + ms).toISOString();
const HOUR = 3_600_000;

function window(overrides: Partial<AccountWindow>): AccountWindow {
  return {
    label: "5 hour",
    minutes: 300,
    utilization: 0.3,
    resets_at: null,
    updated_at: noon.toISOString(),
    reset: false,
    ...overrides,
  };
}

function account(overrides: Partial<EngineAccount>): EngineAccount {
  return {
    id: "a1",
    provider: "claude",
    name: null,
    title: "Personal",
    email: null,
    plan: "Max",
    signed_in: true,
    active: true,
    first: true,
    signing_in: false,
    error: null,
    limits: [],
    checked_at: null,
    banked_resets: null,
    ...overrides,
  };
}

describe("the usage chip", () => {
  it("floors durations to whole units", () => {
    expect(duration(0)).toBe("now");
    expect(duration(-30_000)).toBe("now");
    expect(duration(59_000)).toBe("0m");
    expect(duration((45 * 60 + 59) * 1000)).toBe("45m");
    expect(duration(2 * HOUR)).toBe("2h");
    expect(duration(2 * HOUR + 5.5 * 60_000)).toBe("2h 5m");
    expect(duration(72 * HOUR)).toBe("3d");
    expect(duration(76 * HOUR + 59 * 60_000)).toBe("3d 4h");
  });

  it("shows each window with the time to its reset, the bar for the first", () => {
    const chip = usageChip(
      [
        window({ utilization: 0.3, resets_at: later(2 * HOUR + 5 * 60_000) }),
        window({ label: "Weekly", minutes: 10080, utilization: 0.06, resets_at: later(76 * HOUR) }),
      ],
      noon,
    );
    expect(chip?.windows.map((w) => w.text)).toEqual(["30% 2h 5m", "6% 3d 4h"]);
    expect(chip?.windows.map((w) => w.tooltip)).toEqual([
      "5 hour: 30%, resets in 2h 5m",
      "Weekly: 6%, resets in 3d 4h",
    ]);
    expect(chip?.used).toBe(0.3);
    expect(chip?.tone).toBe("neutral");
  });

  it("names a window's length without a reset time, and turns amber then red", () => {
    const passed = usageChip([window({ utilization: 0.85, reset: true })], noon);
    expect(passed?.windows[0]?.text).toBe("0% 5h");
    expect(usageChip([window({ utilization: 0.85, minutes: 10080 })], noon)?.tone).toBe("amber");
    expect(usageChip([window({ utilization: 0.95, minutes: null })], noon)?.windows[0]?.text).toBe(
      "95%",
    );
    expect(usageChip([window({ utilization: 0.95 })], noon)?.tone).toBe("red");
    expect(usageChip([], noon)).toBeNull();
  });

  it("shows two accounts of one engine with their titles, else Claude without numbers", () => {
    const two = meterLines(
      [
        account({ id: "a1", title: "Personal", limits: [window({})] }),
        account({ id: "a2", title: "Work", active: false }),
      ],
      { ...NO_METER_CHOICE, shown: ["a1", "a2"] },
      noon,
    );
    expect(two.map((l) => [l.title, l.chip === null])).toEqual([
      ["Personal", false],
      ["Work", true],
    ]);
    const none = meterLines([account({ signed_in: false })], NO_METER_CHOICE, noon);
    expect(none).toEqual([
      { id: "claude", provider: "claude", name: "Claude", title: null, chip: null },
    ]);
  });

  // Regression (production check, 2026-11-03): with Codex unable to run, the chip showed a
  // second, empty Codex line.
  it("leaves out an account whose engine cannot run here", () => {
    const lines = meterLines(
      [
        account({ id: "a1", limits: [window({})] }),
        account({ id: "c1", provider: "codex", title: "Codex", signed_in: null }),
      ],
      { ...NO_METER_CHOICE, shown: ["a1", "c1"] },
      noon,
      new Set(["codex"]),
    );
    expect(lines.map((l) => l.id)).toEqual(["a1"]);
  });
});
