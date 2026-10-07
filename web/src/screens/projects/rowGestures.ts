import { useRef, type MouseEvent, type PointerEvent } from "react";

export const LONG_PRESS_MS = 520;
const MOVE_TOLERANCE = 8;
const SWIPE_DISTANCE = 56;

/**
 * A list row's gestures: tap opens; long-press, swipe left or a secondary click show its
 * actions. Spread the result onto the row's button.
 */
export function useRowGestures(onOpen: () => void, onActions: () => void) {
  const press = useRef<{ x: number; y: number; timer: number; handled: boolean } | null>(null);
  // Set when a gesture opened the actions, so the click that follows does not open the row.
  const swallowClick = useRef(false);

  const end = () => {
    const p = press.current;
    press.current = null;
    if (p !== null) window.clearTimeout(p.timer);
    return p;
  };

  return {
    onClick: () => {
      if (swallowClick.current) swallowClick.current = false;
      else onOpen();
    },
    onContextMenu: (event: MouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      end();
      onActions();
    },
    onPointerDown: (event: PointerEvent<HTMLButtonElement>) => {
      if (event.button !== 0) return;
      const p = { x: event.clientX, y: event.clientY, timer: 0, handled: false };
      p.timer = window.setTimeout(() => {
        p.handled = true;
        onActions();
      }, LONG_PRESS_MS);
      press.current = p;
    },
    onPointerMove: (event: PointerEvent<HTMLButtonElement>) => {
      const p = press.current;
      if (p === null) return;
      const dx = event.clientX - p.x;
      if (Math.abs(dx) > MOVE_TOLERANCE || Math.abs(event.clientY - p.y) > MOVE_TOLERANCE) {
        window.clearTimeout(p.timer);
      }
      if (dx < -SWIPE_DISTANCE && !p.handled) {
        p.handled = true;
        onActions();
      }
    },
    onPointerUp: () => {
      swallowClick.current = end()?.handled === true;
    },
    onPointerCancel: () => {
      end();
    },
  };
}
