// The pill eases open and closed as the Mac's IslandScene (B114): open approaches its
// target at 9 times its distance a second, drawn through a quadratic ease, and the list
// fades in from 45% open (B117: ours used its own 280 ms curve and 150 ms fade).
import { describe, expect, it } from "vitest";
import { createScene } from "./pillScene.ts";
import { listAlpha, macEase, OPEN_SETTLE_MS, openAt } from "./pillMotion.ts";

describe("the pill's open and close motion", () => {
  it("settles when the Mac's does, half way at the same moment", () => {
    expect(OPEN_SETTLE_MS).toBe(691);
    // Half drawn when open is half way: ln 2 / 9 s.
    expect(macEase(openAt(77))).toBeCloseTo(0.5, 2);
    expect(macEase(openAt(300))).toBeGreaterThan(0.98);
  });

  it("shows the list from 45% open, and has it gone 89 ms into closing", () => {
    expect(listAlpha(0.45)).toBe(0);
    expect(listAlpha(1)).toBe(1);
    expect(listAlpha(1 - openAt(89))).toBeCloseTo(0, 2);
  });

  it("is stepped by the scene: open in about 0.7 s, at once under Reduce Motion", () => {
    const at = (reduce: boolean) => ({
      left: [],
      right: [],
      sideWidth: 76,
      wantsOpen: true,
      reduce,
    });
    const scene = createScene();
    let frame = scene.step(0, at(false));
    for (let t = 16; t <= 304; t += 16) frame = scene.step(t, at(false));
    expect(frame.eased).toBeGreaterThan(0.98);
    expect(frame.open).toBeLessThan(1);
    for (let t = 320; t <= 720; t += 16) frame = scene.step(t, at(false));
    expect(frame.open).toBe(1);
    const reduced = createScene();
    reduced.step(0, { ...at(true), wantsOpen: false });
    expect(reduced.step(16, at(true)).open).toBe(1);
  });
});
