// The pill window's size against what it draws (B117): the window grows downward before
// the pill eases open in it, and shrinks only after the pill eased closed, so no frame shows
// the list cut off. What takes clicks (the window's input shape) is the pill's new size at
// once, so a pill easing closed lets clicks through to the window below, as the Mac's
// island ignores the pointer outside its strip and open list. The Mac's island draws in a
// fixed panel; here each window resize is a round trip to the window manager.

import { OPEN_SETTLE_MS } from "./pillMotion.ts";

// As long as the pill takes to ease open, closed, wider or narrower (pillMotion.ts).
export const PILL_EASE_MS = OPEN_SETTLE_MS;
// The window shrinks this long after the pill began to ease closed: once it has.
export const WINDOW_SHRINK_MS = PILL_EASE_MS + 40;

// The Mac's pill (IslandLayout.swift): 28 point sprites in 30 point slots after an 8 point
// pad, at most three a side then a 24 point +N, 12 points from the centre to each side.
const SLOT = 30;
const PAD = 8;
const PLUS = 24;
const MOST = 3;
const CENTRE_GAP = 12;
const SMALLEST = 28 + 12;
// The pill's sides are even and never narrower than two sprites and a margin.
const SIDE_MIN = 28 * 2 + 20;

function sideWidth(count: number, extra: number): number {
  const shown = Math.min(MOST, count);
  return Math.max(SMALLEST, PAD + shown * SLOT + (count > shown ? PLUS : 0) + extra);
}

/**
 * The strip's width for this many figures on the left and on the right (Nightshade and the
 * resting Bluebell count as one), as IslandLayout.fit for the pill: both sides as wide as
 * the wider, the left with 2 points to spare, the right with 6 for its badges.
 */
export function pillStripWidth(
  left: number,
  right: number,
): {
  side: number;
  width: number;
} {
  const side = Math.max(SIDE_MIN, sideWidth(left, 2), sideWidth(right, 6));
  return { side, width: side * 2 + CENTRE_GAP * 2 };
}

export interface PillSize {
  width: number;
  height: number;
}

/** What the window is asked for: the pill's shape, which takes clicks, and its height. */
export interface PillFrame extends PillSize {
  room: number;
}

export interface PillSizer {
  // The size the pill should draw: the strip, or the strip with its open list; and the
  // least height the window needs below it, for a pixie flying under the strip.
  want(size: PillSize, below?: number): void;
  dispose(): void;
}

interface Clock {
  later(run: () => void, ms: number): number;
  cancel(id: number): void;
  // After the window manager applied a resize: the next frame.
  frame(run: () => void): void;
}

const browserClock: Clock = {
  later: (run, ms) => window.setTimeout(run, ms),
  cancel: (id) => {
    window.clearTimeout(id);
  },
  frame: (run) => {
    window.requestAnimationFrame(() => {
      run();
    });
  },
};

const same = (a: PillSize | null, b: PillSize | null) =>
  a !== null && b !== null && a.width === b.width && a.height === b.height;

export function pillSizer(
  resize: (frame: PillFrame) => Promise<void>,
  draw: (size: PillSize) => void,
  clock: Clock = browserClock,
): PillSizer {
  // The window's height as last asked.
  let room: number | null = null;
  let target: PillSize | null = null;
  let targetBelow = 0;
  let shrinking: number | null = null;
  let disposed = false;

  const stopShrinking = () => {
    if (shrinking !== null) clock.cancel(shrinking);
    shrinking = null;
  };

  return {
    want(size, below = 0) {
      if (same(size, target) && below === targetBelow) return;
      const resized = !same(size, target);
      target = size;
      targetBelow = below;
      stopShrinking();
      const needed = Math.max(size.height, below);
      if (room === null || needed > room) {
        // Grow first; draw once there is room.
        room = needed;
        void resize({ ...size, room }).then(() => {
          if (disposed) return;
          clock.frame(() => {
            if (!disposed && same(target, size)) draw(size);
          });
        });
        return;
      }
      if (resized) {
        void resize({ ...size, room });
        draw(size);
      }
      if (needed === room) return;
      shrinking = clock.later(() => {
        shrinking = null;
        if (disposed || !same(target, size) || below !== targetBelow) return;
        room = needed;
        void resize({ ...size, room });
      }, WINDOW_SHRINK_MS);
    },
    dispose() {
      disposed = true;
      stopShrinking();
    },
  };
}
