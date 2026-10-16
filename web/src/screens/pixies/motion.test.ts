import { describe, expect, it } from "vitest";
import { BLINK_MS, fourFaces, HOP_MS, phaseOffset, STEP_MS } from "./motion.ts";

describe("the working sprite's clock (B48)", () => {
  it("steps every 170 ms, hops every four steps and blinks every third hop", () => {
    expect([STEP_MS, HOP_MS, BLINK_MS]).toEqual([170, 680, 2040]);
  });

  it("offsets each key by a stable amount within one blink cycle", () => {
    const keys = ["p1", "p2", "scribe", "lead", "bugs", "a", ""];
    const offsets = keys.map(phaseOffset);
    expect(keys.map(phaseOffset)).toEqual(offsets);
    for (const offset of offsets) {
      expect(Number.isInteger(offset)).toBe(true);
      expect(offset).toBeGreaterThanOrEqual(0);
      expect(offset).toBeLessThan(BLINK_MS);
    }
    // Different keys land on different phases, so sprites do not hop in lockstep.
    expect(new Set(offsets).size).toBe(offsets.length);
  });
});

describe("a team's grid of four (B48)", () => {
  const member = (id: string, leader = false) => ({ pixie_id: id, leader });
  const ids = (members: { pixie_id: string }[]) => members.map((m) => m.pixie_id).join(" ");

  it("puts the leader first, then the others in team order", () => {
    expect(ids(fourFaces([member("a"), member("b"), member("c", true), member("d")]))).toBe(
      "c a b d",
    );
  });

  it("repeats the members in order to fill four cells", () => {
    expect(ids(fourFaces([member("a", true)]))).toBe("a a a a");
    expect(ids(fourFaces([member("b"), member("a", true)]))).toBe("a b a b");
    expect(ids(fourFaces([member("a", true), member("b"), member("c")]))).toBe("a b c a");
  });

  it("shows the leader and the next three of a bigger team", () => {
    const team = ["a", "b", "c", "d", "e"].map((id) => member(id, id === "e"));
    expect(ids(fourFaces(team))).toBe("e a b c");
  });

  it("keeps team order without a leader, and is empty without members", () => {
    expect(ids(fourFaces([member("a"), member("b")]))).toBe("a b a b");
    expect(fourFaces([])).toEqual([]);
  });
});
