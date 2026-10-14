import { useRef, useState, type PointerEvent } from "react";

export const SWIPE_THRESHOLD = 90;
const LOCK_DISTANCE = 8;

interface Gesture {
  x: number;
  y: number;
  lock: "x" | "y" | null;
  dx: number;
}

/**
 * Horizontal swipe on a card: right past the threshold calls onRight, left calls onLeft.
 * A vertical move hands the gesture back to scrolling. Buttons and fields never start one,
 * and nothing does while `busy`, so a second swipe cannot send the answer twice.
 */
export function useSwipe(onRight: () => void, onLeft: () => void, busy = false) {
  const gesture = useRef<Gesture | null>(null);
  const [dx, setDx] = useState(0);

  const reset = () => {
    gesture.current = null;
    setDx(0);
  };

  const handlers = {
    onPointerDown: (event: PointerEvent<HTMLElement>) => {
      const target = event.target as HTMLElement;
      if (busy || event.button !== 0 || target.closest("button, input, textarea, a") !== null) {
        return;
      }
      gesture.current = { x: event.clientX, y: event.clientY, lock: null, dx: 0 };
    },
    onPointerMove: (event: PointerEvent<HTMLElement>) => {
      const g = gesture.current;
      if (g === null) return;
      const moveX = event.clientX - g.x;
      const moveY = event.clientY - g.y;
      if (g.lock === null) {
        if (Math.max(Math.abs(moveX), Math.abs(moveY)) <= LOCK_DISTANCE) return;
        g.lock = Math.abs(moveX) > Math.abs(moveY) ? "x" : "y";
      }
      if (g.lock === "y") return;
      g.dx = moveX;
      setDx(moveX);
    },
    onPointerUp: () => {
      const moved = gesture.current?.dx ?? 0;
      reset();
      if (moved > SWIPE_THRESHOLD) onRight();
      else if (moved < -SWIPE_THRESHOLD) onLeft();
    },
    onPointerCancel: reset,
  };

  return { dx, handlers };
}
