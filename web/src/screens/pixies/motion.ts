import { useSyncExternalStore } from "react";

// A working sprite's clock (B48), the same as the Mac app's: hard steps of 170 ms, a hop
// of four steps (up for the middle two), a blink on every third hop. The stylesheet's
// pxhop and pxblink keyframes follow these numbers.
export const STEP_MS = 170;
export const HOP_MS = 4 * STEP_MS;
export const BLINK_MS = 3 * HOP_MS;

/** A stable start within the blink cycle for `key`, so sprites do not hop in lockstep. */
export function phaseOffset(key: string): number {
  // FNV-1a, 32 bit.
  let hash = 0x811c9dc5;
  for (let i = 0; i < key.length; i++) {
    hash = Math.imul(hash ^ key.charCodeAt(i), 0x01000193) >>> 0;
  }
  return hash % BLINK_MS;
}

const REDUCE = "(prefers-reduced-motion: reduce)";

function query(): MediaQueryList | undefined {
  const { matchMedia } = window as { matchMedia?: Window["matchMedia"] };
  return matchMedia?.(REDUCE);
}

function subscribe(onChange: () => void): () => void {
  const list = query();
  list?.addEventListener("change", onChange);
  return () => {
    list?.removeEventListener("change", onChange);
  };
}

/** Whether the user asked for less motion (Reduce Motion), following changes. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, () => query()?.matches === true);
}

/**
 * A team's four faces (B48): the leader first, then the others in team order, repeated
 * to fill four cells when the team is smaller, and cut to four when it is bigger.
 */
export function fourFaces<T extends { leader: boolean }>(members: readonly T[]): T[] {
  const ordered = [...members.filter((m) => m.leader), ...members.filter((m) => !m.leader)];
  if (ordered.length === 0) return [];
  let cells = ordered;
  while (cells.length < 4) cells = [...cells, ...ordered];
  return cells.slice(0, 4);
}
