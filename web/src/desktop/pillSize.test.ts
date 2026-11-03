// Regression (B117 audit): the pill flickered as it opened and closed, the window and the
// list changing size out of step. The window grows before the pill eases open in it, and
// shrinks only after the pill eased closed; what takes clicks follows the pill at once.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  PILL_EASE_MS,
  pillSizer,
  pillStripWidth,
  WINDOW_SHRINK_MS,
  type PillFrame,
  type PillSize,
} from "./pillSize.ts";

afterEach(() => {
  vi.useRealTimers();
});

function setup() {
  vi.useFakeTimers();
  const resize = vi.fn<(frame: PillFrame) => Promise<void>>().mockResolvedValue(undefined);
  const draw = vi.fn<(size: PillSize) => void>();
  const sizer = pillSizer(resize, draw, {
    later: (run, ms) => Number(setTimeout(run, ms)),
    cancel: (id) => {
      clearTimeout(id);
    },
    frame: (run) => {
      setTimeout(run, 0);
    },
  });
  return { resize, draw, sizer };
}

const flush = async () => {
  await vi.advanceTimersByTimeAsync(0);
};

const STRIP = { width: 176, height: 34 };
const OPEN = { width: 420, height: 150 };

// Ported from NestKitTests' IslandLayoutTests.thePillKeepsBothSidesEven.
describe("the pill's strip", () => {
  it("keeps both sides even, as wide as the wider", () => {
    // Nightshade and the resting Bluebell: the smallest pill.
    expect(pillStripWidth(1, 1)).toEqual({ side: 76, width: 176 });
    expect(pillStripWidth(1, 3)).toEqual({ side: 104, width: 232 });
    // Three a side, then the +N beside them.
    expect(pillStripWidth(5, 2).side).toBe(8 + 3 * 30 + 24 + 2);
  });
});

describe("the pill window's size", () => {
  it("grows the window before drawing the open list", async () => {
    const { resize, draw, sizer } = setup();
    sizer.want(STRIP);
    await flush();
    expect(resize).toHaveBeenLastCalledWith({ ...STRIP, room: 34 });
    expect(draw).toHaveBeenLastCalledWith(STRIP);
    sizer.want(OPEN);
    expect(resize).toHaveBeenLastCalledWith({ ...OPEN, room: 150 });
    expect(draw).not.toHaveBeenCalledWith(OPEN);
    await flush();
    expect(draw).toHaveBeenLastCalledWith(OPEN);
  });

  // Regression (B117 VM check): while the list eased closed the window still took clicks
  // where the list had been, so a click on Nest's window below did nothing.
  it("takes clicks only on the strip at once as it closes, then shrinks the window", async () => {
    const { resize, draw, sizer } = setup();
    sizer.want(OPEN);
    await flush();
    resize.mockClear();
    sizer.want(STRIP);
    expect(draw).toHaveBeenLastCalledWith(STRIP);
    expect(resize.mock.calls).toEqual([[{ ...STRIP, room: 150 }]]);
    await vi.advanceTimersByTimeAsync(WINDOW_SHRINK_MS - 1);
    expect(resize).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(resize).toHaveBeenLastCalledWith({ ...STRIP, room: 34 });
  });

  // A pixie changing side flies under the strip (IslandScene's flight): the window makes
  // room below while clicks still land on the strip only, and gives it back after.
  it("keeps room below the strip for a flight without taking clicks there", async () => {
    const { resize, draw, sizer } = setup();
    sizer.want(STRIP);
    await flush();
    resize.mockClear();
    draw.mockClear();
    sizer.want(STRIP, 84);
    expect(resize.mock.calls).toEqual([[{ ...STRIP, room: 84 }]]);
    sizer.want(STRIP, 0);
    await vi.advanceTimersByTimeAsync(WINDOW_SHRINK_MS);
    expect(resize).toHaveBeenLastCalledWith({ ...STRIP, room: 34 });
  });

  it("opening again while it closes keeps the window and draws at once", async () => {
    const { resize, draw, sizer } = setup();
    sizer.want(OPEN);
    await flush();
    sizer.want(STRIP);
    await vi.advanceTimersByTimeAsync(PILL_EASE_MS / 2);
    resize.mockClear();
    sizer.want(OPEN);
    expect(draw).toHaveBeenLastCalledWith(OPEN);
    await vi.advanceTimersByTimeAsync(WINDOW_SHRINK_MS * 2);
    // The window never shrank: only the shape came back.
    expect(resize.mock.calls).toEqual([[{ ...OPEN, room: 150 }]]);
  });
});
