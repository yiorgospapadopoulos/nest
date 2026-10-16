import { act } from "@testing-library/react";
import { vi } from "vitest";

/** A media query answer that never changes, as `matchMedia` gives it. */
export function fixedMedia(matches: boolean) {
  return { matches, addEventListener: () => undefined, removeEventListener: () => undefined };
}

/**
 * Reduce Motion on or off, with a way to flip it as the system setting would. It stubs
 * `matchMedia`; the test file undoes it with `vi.unstubAllGlobals()`.
 */
export function reduceMotion(on: boolean) {
  const listeners = new Set<() => void>();
  const list = {
    matches: on,
    addEventListener: (_: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
  };
  vi.stubGlobal("matchMedia", (query: string) =>
    query === "(prefers-reduced-motion: reduce)" ? list : { ...list, matches: false },
  );
  return {
    listeners,
    flip(value: boolean) {
      list.matches = value;
      act(() => {
        for (const listener of listeners) listener();
      });
    },
  };
}
