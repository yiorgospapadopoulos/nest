// The pill's moving parts follow the Mac's IslandScene (B114): flights under the strip,
// the drop-in, the fade and the pop as pixies leave, places and widths easing, and none of
// it under Reduce Motion (B117: the Linux pill jumped between states).
import { describe, expect, it } from "vitest";
import {
  createScene,
  DIP,
  FLIGHT_MS,
  LEAVE_MS,
  leaving,
  plusX,
  SLOT,
  SPRITE,
  SPRITE_TOP,
  type SceneInput,
  type SceneItem,
} from "./pillScene.ts";

const item = (id: string, landing: SceneItem["landing"] = "none"): SceneItem => ({
  id,
  color: "#12A594",
  landing,
  data: null,
});
const input = (left: SceneItem[], right: SceneItem[], extra: Partial<SceneInput> = {}) => ({
  left,
  right,
  sideWidth: 76,
  wantsOpen: false,
  reduce: false,
  ...extra,
});

/** Steps the scene in 16 ms frames from `from` to `to`, returning the last frame. */
function run(scene: ReturnType<typeof createScene>, from: number, to: number, at: SceneInput) {
  let frame = scene.step(from, at);
  for (let t = from + 16; t <= to; t += 16) frame = scene.step(t, at);
  return frame;
}
const sprite = (frame: ReturnType<ReturnType<typeof createScene>["step"]>, id: string) =>
  frame.sprites.find((s) => s.id === id);

describe("the pill's scene", () => {
  it("drops a new pixie in from above the strip, then rests in its place", () => {
    const scene = createScene(() => 0.5);
    const first = scene.step(0, input([item("a")], []));
    expect(sprite(first, "a")?.y).toBe(-SPRITE - 4);
    const later = run(scene, 16, 1500, input([item("a")], []));
    expect(sprite(later, "a")?.y).toBe(SPRITE_TOP);
    expect(later.moving).toBe(false);
  });

  it("flies a pixie that changes side under the strip for 1.3 s, then lands with a burst", () => {
    const scene = createScene(() => 0.5);
    run(scene, 0, 1500, input([item("a")], []));
    const done = input([], [item("a", "done")]);
    const half = run(scene, 1516, 1516 + FLIGHT_MS / 2, done);
    const flying = sprite(half, "a");
    expect(flying?.flying).toBe(true);
    // Half way it is at the bottom of its dip, below the strip.
    expect(flying?.y).toBeGreaterThan(DIP - 2);
    expect(half.under).toBe(true);
    expect(half.particles.some((p) => p.free)).toBe(true);
    const landed = run(scene, 1516 + FLIGHT_MS / 2 + 16, 1516 + FLIGHT_MS + 16, done);
    expect(sprite(landed, "a")?.flying).toBe(false);
    expect(sprite(landed, "a")?.x).toBe(12 + 8);
    expect(sprite(landed, "a")?.arrived).toBeGreaterThanOrEqual(1516 + FLIGHT_MS);
    expect(landed.particles.filter((p) => !p.free).length).toBe(10);
  });

  it("fades a pixie that leaves for 300 ms, rising", () => {
    const scene = createScene(() => 0.5);
    run(scene, 0, 1500, input([], [item("a")]));
    const gone = input([], []);
    const fading = run(scene, 1516, 1516 + LEAVE_MS / 2, gone);
    const s = sprite(fading, "a");
    expect(s?.leaving).toBe(true);
    expect(s?.alpha).toBeCloseTo(0.5, 1);
    expect(s?.y).toBeLessThan(SPRITE_TOP);
    const after = run(scene, 1516 + LEAVE_MS / 2 + 16, 1516 + LEAVE_MS + 32, gone);
    expect(sprite(after, "a")).toBeUndefined();
  });

  it("pops a pixie a click sent away: gone at once in a burst of 22", () => {
    const scene = createScene(() => 0.5);
    run(scene, 0, 1500, input([], [item("a")]));
    scene.pop("a");
    const frame = scene.step(1516, input([], []));
    expect(sprite(frame, "a")).toBeUndefined();
    expect(frame.particles.length).toBe(22);
  });

  it("eases a pixie to its new place when the side reflows, and the side's width", () => {
    const scene = createScene(() => 0.5);
    run(scene, 0, 1500, input([item("a"), item("b")], []));
    // a leaves: b moves into the first slot, the side keeps its width while it eases.
    const next = input([item("b")], [], { sideWidth: 60 });
    const soon = scene.step(1516, next);
    const b = sprite(soon, "b");
    expect(b?.x).toBeGreaterThan(-12 - 76 + 8);
    expect(soon.leftWidth).toBeLessThan(76);
    expect(soon.leftWidth).toBeGreaterThan(60);
    const settled = run(scene, 1532, 3000, next);
    expect(settled.leftWidth).toBe(60);
    expect(sprite(settled, "b")?.x).toBe(-12 - 60 + 8);
  });

  it("folds a fourth pixie into the +N", () => {
    const scene = createScene(() => 0.5);
    const four = input([item("a"), item("b"), item("c"), item("d")], []);
    const frame = run(scene, 0, 2000, four);
    expect(sprite(frame, "d")).toBeUndefined();
    expect(frame.sprites.filter((s) => !s.leaving).length).toBe(3);
    expect(plusX("left", 76, 3)).toBe(-12 - 76 + 8 + 3 * SLOT + 3);
  });

  it("moves nothing under Reduce Motion: no drop-in, flight, burst or trail", () => {
    const scene = createScene(() => 0.5);
    const reduce = { reduce: true };
    const first = scene.step(0, input([item("a")], [], reduce));
    expect(sprite(first, "a")?.y).toBe(SPRITE_TOP);
    const moved = scene.step(16, input([], [item("a", "done")], reduce));
    expect(sprite(moved, "a")?.flying).toBe(false);
    expect(sprite(moved, "a")?.x).toBe(20);
    expect(moved.particles.length).toBe(0);
    scene.pop("a");
    expect(scene.step(32, input([], [], reduce)).particles.length).toBe(0);
  });
});

describe("how a pixie leaves the pill", () => {
  it("pops when its chat was seen after it finished, else fades", () => {
    expect(leaving("done", 100, 150)).toBe("pop");
    expect(leaving("failed", 100, 100)).toBe("pop");
    expect(leaving("done", 100, undefined)).toBe("fade");
    // Working, or needing the user, it just fades.
    expect(leaving("working", 100, 150)).toBe("fade");
    expect(leaving("needsYou", 100, 150)).toBe("fade");
  });
});
