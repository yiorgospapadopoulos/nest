import { useRef, type MouseEvent, type PointerEvent } from "react";

// Further than this between press and release is a drag, not a tap.
export const TAP_SLOP = 4;

/**
 * A press and release on the same spot acts on the release, and the click that may follow
 * is left alone; a click with no pointer (Enter or Space) acts on its own. WebKitGTK sends
 * no click for a press with no time before the release on elements with drag handling (a
 * zero-length xdotool click or a quick touchpad tap, B117), so nothing here relies on it.
 */
export function useTap(onTap: () => void) {
  const start = useRef<{ x: number; y: number } | null>(null);
  return {
    onPointerDown: (event: PointerEvent<HTMLElement>) => {
      start.current = event.button === 0 ? { x: event.clientX, y: event.clientY } : null;
    },
    onPointerUp: (event: PointerEvent<HTMLElement>) => {
      const from = start.current;
      start.current = null;
      if (from === null || event.button !== 0) return;
      const moved = Math.hypot(event.clientX - from.x, event.clientY - from.y);
      if (moved <= TAP_SLOP) onTap();
    },
    // A drag that took over (HTML drag and drop) ends the press without a tap.
    onPointerCancel: () => {
      start.current = null;
    },
    onClick: (event: MouseEvent<HTMLElement>) => {
      if (event.detail === 0) onTap();
    },
  };
}
