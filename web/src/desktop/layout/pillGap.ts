// The room the tab strip leaves for the pixie pill (B117, user 2026-11-03): the pill stays
// at the top centre of the screen, so when the window's top is under it the strip keeps a
// gap there, tabs to its left and the usage meter and search to its right, as the Mac's
// menu bar items avoid the notch.

export interface ScreenRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

// Where the Tauri side keeps the pill: centred, this far from the screen's top.
export const PILL_TOP = 8;
// The widest strip, three figures and a +N a side (pillSize.ts pillStripWidth), and its
// height; a quieter pill is narrower inside the same gap.
export const PILL_WIDTH = 272;
export const PILL_HEIGHT = 34;
// Clear space on each side of the pill.
export const GAP_MARGIN = 8;

/** The pill's strip on a screen that starts at `left` and is `width` wide (CSS pixels). */
export function pillRect(left: number, width: number): ScreenRect {
  return {
    x: left + (width - PILL_WIDTH) / 2,
    y: PILL_TOP,
    width: PILL_WIDTH,
    height: PILL_HEIGHT,
  };
}

/** The strip's room left of the gap and right of it, in pixels. */
export interface StripGap {
  left: number;
  width: number;
  right: number;
}

/**
 * The gap in the strip, from the window's left edge, when the pill covers part of the
 * strip (`window` is the strip's rectangle on screen); null when it does not.
 */
export function stripGap(window: ScreenRect, pill: ScreenRect): StripGap | null {
  const below = pill.y + pill.height <= window.y || pill.y >= window.y + window.height;
  const beside = pill.x + pill.width <= window.x || pill.x >= window.x + window.width;
  if (below || beside) return null;
  const left = Math.max(0, pill.x - GAP_MARGIN - window.x);
  const end = Math.min(window.width, pill.x + pill.width + GAP_MARGIN - window.x);
  return { left, width: end - left, right: window.width - end };
}
