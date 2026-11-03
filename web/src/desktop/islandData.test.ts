// Regression (B117 VM check): a pixie that finished in the chat you were looking at left
// the pill at once, with no landing: the main window marked the chat seen the moment the
// call changed. D140: it flies to the right, lands, then pops.
import { describe, expect, it } from "vitest";
import { callEntry, groupEntry } from "../test/fixtures.ts";
import { LAND_MS, seenDelay } from "./islandData.ts";

const now = Date.parse("2027-01-15T08:00:00Z");
const ago = (ms: number) => new Date(now - ms).toISOString();

describe("when the focused chat counts as seen", () => {
  it("waits for a pixie that just finished to land", () => {
    const groups = [groupEntry({ calls: [callEntry({ state: "done", finished_at: ago(1000) })] })];
    expect(seenDelay(groups, now)).toBe(LAND_MS - 1000);
  });

  it("is at once for calls that finished long ago, run on or wait for the user", () => {
    expect(seenDelay(undefined, now)).toBe(0);
    const old = callEntry({ state: "done", finished_at: ago(LAND_MS * 10) });
    const running = callEntry({ id: "c2", state: "running", finished_at: null });
    expect(seenDelay([groupEntry({ calls: [old, running] })], now)).toBe(0);
  });

  it("never waits longer than a landing, even with the daemon's clock ahead", () => {
    const groups = [groupEntry({ calls: [callEntry({ finished_at: ago(-60_000) })] })];
    expect(seenDelay(groups, now)).toBe(LAND_MS);
  });
});
