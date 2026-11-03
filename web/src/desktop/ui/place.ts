// Where a menu or popover goes: next to what opened it, flipped to the other side when it
// does not fit, and kept inside the window, as AppKit places its menus and popovers.

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface Size {
  width: number;
  height: number;
}

// Below or above the anchor, or beside it (a submenu); `align` lines up its edges.
export type Side = "below" | "above" | "right";
export type Align = "start" | "center" | "end";

// Kept this far from the window's edges.
export const EDGE = 6;
// Between the anchor and what opens from it.
export const GAP = 4;

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(value, Math.max(min, max)));
}

/** The top left corner for `size` opened from `anchor` inside `view`. */
export function anchored(
  anchor: Box,
  size: Size,
  view: Size,
  side: Side = "below",
  align: Align = "start",
): { left: number; top: number } {
  if (side === "right") {
    // A submenu: beside its row, its first item level with it, else on the left.
    const right = anchor.left + anchor.width - 2;
    const fits = right + size.width <= view.width - EDGE;
    const left = fits ? right : anchor.left - size.width + 2;
    return {
      left: clamp(left, EDGE, view.width - EDGE - size.width),
      top: clamp(anchor.top - GAP, EDGE, view.height - EDGE - size.height),
    };
  }
  const below = anchor.top + anchor.height + GAP;
  const above = anchor.top - GAP - size.height;
  const roomBelow = view.height - EDGE - below;
  const roomAbove = above - EDGE;
  let top: number;
  if (side === "below") top = size.height <= roomBelow || roomBelow >= roomAbove ? below : above;
  else top = size.height <= anchor.top - GAP - EDGE || roomAbove >= roomBelow ? above : below;
  let left = anchor.left;
  if (align === "center") left = anchor.left + (anchor.width - size.width) / 2;
  if (align === "end") left = anchor.left + anchor.width - size.width;
  return {
    left: clamp(left, EDGE, view.width - EDGE - size.width),
    top: clamp(top, EDGE, view.height - EDGE - size.height),
  };
}

/** A context menu's corner: at the pointer, moved left or up when it would leave the window. */
export function atPoint(
  point: { x: number; y: number },
  size: Size,
  view: Size,
): { left: number; top: number } {
  const left = point.x + size.width <= view.width - EDGE ? point.x : point.x - size.width;
  const top = point.y + size.height <= view.height - EDGE ? point.y : point.y - size.height;
  return {
    left: clamp(left, EDGE, view.width - EDGE - size.width),
    top: clamp(top, EDGE, view.height - EDGE - size.height),
  };
}
