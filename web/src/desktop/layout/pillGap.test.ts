// The tab strip keeps clear of the pill only where the pill covers it.
import { describe, expect, it } from "vitest";
import { pillRect, stripGap } from "./pillGap.ts";

// A 1280 wide screen: the pill spans 504 to 776, from 8 to 42.
const pill = pillRect(0, 1280);

describe("the strip's gap for the pill", () => {
  it("opens over the pill for a maximised window under the top bar", () => {
    expect(pill).toEqual({ x: 504, y: 8, width: 272, height: 34 });
    expect(stripGap({ x: 0, y: 32, width: 1280, height: 40 }, pill)).toEqual({
      left: 496,
      width: 288,
      right: 496,
    });
  });

  it("follows the window's left edge and stops at its sides", () => {
    expect(stripGap({ x: 200, y: 0, width: 900, height: 40 }, pill)).toEqual({
      left: 296,
      width: 288,
      right: 316,
    });
    // Only the pill's right end is over a window that starts at 700.
    expect(stripGap({ x: 700, y: 0, width: 500, height: 40 }, pill)).toEqual({
      left: 0,
      width: 84,
      right: 416,
    });
  });

  it("is not there when the window's strip is below or beside the pill", () => {
    expect(stripGap({ x: 0, y: 42, width: 1280, height: 40 }, pill)).toBeNull();
    expect(stripGap({ x: 0, y: 300, width: 1280, height: 40 }, pill)).toBeNull();
    expect(stripGap({ x: 780, y: 0, width: 400, height: 40 }, pill)).toBeNull();
  });
});
