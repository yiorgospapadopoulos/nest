/**
 * Keeps the phone app from zooming, as a native app would. iPhone Safari ignores
 * `user-scalable=no` for pinches, so its own pinch events are cancelled here.
 */

export type GestureTarget = Pick<EventTarget, "addEventListener">;

const PINCH_EVENTS = ["gesturestart", "gesturechange"] as const;

export function preventZoom(target: GestureTarget): void {
  for (const type of PINCH_EVENTS) {
    target.addEventListener(
      type,
      (event) => {
        event.preventDefault();
      },
      { passive: false },
    );
  }
}
