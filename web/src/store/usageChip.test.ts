import { describe, expect, it } from "vitest";
import { accountList, accountWindow, codexAccount, engineAccount } from "../test/accounts.ts";
import { chipEntries, NO_METER_CHOICE } from "./usageMeter.ts";

// The Chats header's usage (B116 option A): the top two checked accounts, each as its
// shortest window, in the Mac chip's words.

const NOW = new Date("2026-11-02T20:00:00Z");
const at = (minutes: number) => new Date(NOW.getTime() + minutes * 60_000).toISOString();

describe("chipEntries", () => {
  it("shows the account in use of each engine by default, as its shortest window", () => {
    const accounts = [
      engineAccount({
        limits: [
          accountWindow({
            label: "Weekly",
            minutes: 10080,
            utilization: 0.07,
            resets_at: at(6 * 1440),
          }),
          accountWindow({ utilization: 0.634, resets_at: at(125) }),
        ],
      }),
      engineAccount({ id: "claude-work", active: false, first: false }),
      codexAccount({ limits: [accountWindow({ utilization: 0.01, resets_at: at(45) })] }),
    ];
    expect(chipEntries(accounts, NO_METER_CHOICE, NOW)).toEqual([
      // The phone's header has room for the largest unit only (the Mac says "2h 5m").
      { id: "claude-main", provider: "claude", text: "63% 2h", used: 0.634, tone: "ok" },
      { id: "codex-main", provider: "codex", text: "1% 45m", used: 0.01, tone: "ok" },
    ]);
  });

  it("follows the user's order and checks, at most two, skipping signed-out ones", () => {
    const accounts = accountList();
    accounts[2] = codexAccount({ signed_in: false });
    const choice = {
      order: ["codex-main", "claude-work"],
      shown: ["claude-work", "claude-main", "codex-main"],
      hiddenEngines: [],
    };
    expect(chipEntries(accounts, choice, NOW).map((e) => e.id)).toEqual([
      "claude-work",
      "claude-main",
    ]);
  });

  it("warns from 80 percent and alarms from 90, and says now once a window is due", () => {
    const at80 = engineAccount({
      limits: [accountWindow({ utilization: 0.8, resets_at: at(-1) })],
    });
    const at90 = codexAccount({ limits: [accountWindow({ utilization: 0.95 })] });
    expect(chipEntries([at80, at90], NO_METER_CHOICE, NOW)).toEqual([
      { id: "claude-main", provider: "claude", text: "80% now", used: 0.8, tone: "warn" },
      // No reset time reported: the window's length instead, as the Mac's chip.
      { id: "codex-main", provider: "codex", text: "95% 5h", used: 0.95, tone: "bad" },
    ]);
  });

  it("shows nothing for an account that reported no window yet", () => {
    expect(chipEntries([engineAccount({ limits: [] })], NO_METER_CHOICE, NOW)).toEqual([]);
  });
});
