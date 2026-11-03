// How the pill eases open and closed, from the Mac's IslandScene.render: each frame `open`
// moves toward its target by min(1, dt * 9), the shape is drawn at ease(open), and the
// list fades in as (open - 0.45) / 0.55. The scene steps it (pillScene.ts).

// The Mac's rate: open closes 9 times its distance to the target per second.
export const OPEN_RATE = 9;
// It settles once within 0.002 of the target.
export const OPEN_SETTLE_MS = Math.round((Math.log(1 / 0.002) / OPEN_RATE) * 1000);

/** IslandScene.ease: quadratic in and out. */
export function macEase(p: number): number {
  return p < 0.5 ? 2 * p * p : 1 - (-2 * p + 2) ** 2 / 2;
}

/** How far `open` has come `ms` after it started toward its target, 0 to 1. */
export function openAt(ms: number): number {
  return 1 - Math.exp((-OPEN_RATE * ms) / 1000);
}

/** The list's opacity at `open`. */
export function listAlpha(open: number): number {
  return Math.max(0, (open - 0.45) / 0.55);
}
