import type { Mascot } from "../../api/types.ts";
import { MASCOT_SPRITES } from "../../generated/mascots.ts";

export type Cell = readonly [x: number, y: number];

/** How a mascot blinks: its eye holes fill, or (without holes) its lone eye cells go out. */
export interface Blink {
  mode: "fill" | "hide";
  // Row by row, then left to right.
  cells: Cell[];
}

// An enclosed empty region this small may be an eye; a bigger one is a face.
const MAX_EYE = 6;
const NEIGHBOURS: readonly Cell[] = [
  [1, 0],
  [-1, 0],
  [0, 1],
  [0, -1],
];

const byRow = (a: Cell, b: Cell) => a[1] - b[1] || a[0] - b[0];

/**
 * The cells a grid ("#" filled, "." empty) blinks, the same rule as the Mac app (B48):
 * of the small enclosed holes, those starting on the topmost row are the eyes, so mouths
 * and spots lower down stay as they are.
 */
export function blinkOf(rows: readonly string[]): Blink {
  const filled = (x: number, y: number) => rows[y]?.charAt(x) === "#";
  const inside = (x: number, y: number) => {
    const row = rows[y];
    return row !== undefined && x >= 0 && x < row.length;
  };
  const seen = new Set<string>();
  const eyes: Cell[] = [];
  let top: number | null = null;
  rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      if (filled(x, y) || seen.has(`${String(x)},${String(y)}`)) continue;
      // Flood the empty region from here, noting whether it reaches the border.
      const region: Cell[] = [];
      let open = false;
      const queue: Cell[] = [[x, y]];
      seen.add(`${String(x)},${String(y)}`);
      for (let cell = queue.shift(); cell !== undefined; cell = queue.shift()) {
        region.push(cell);
        for (const [dx, dy] of NEIGHBOURS) {
          const nx = cell[0] + dx;
          const ny = cell[1] + dy;
          const key = `${String(nx)},${String(ny)}`;
          if (!inside(nx, ny)) open = true;
          else if (!filled(nx, ny) && !seen.has(key)) {
            seen.add(key);
            queue.push([nx, ny]);
          }
        }
      }
      if (open || region.length > MAX_EYE) continue;
      // Scanning row by row, the first hole found starts on the topmost row.
      top ??= y;
      if (y === top) eyes.push(...region);
    }
  });
  if (eyes.length > 0) return { mode: "fill", cells: eyes.sort(byRow) };
  const lone: Cell[] = [];
  rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      if (filled(x, y) && NEIGHBOURS.every(([dx, dy]) => !filled(x + dx, y + dy))) {
        lone.push([x, y]);
      }
    }
  });
  return { mode: "hide", cells: lone };
}

/** Each mascot's blink, worked out once. */
export const BLINKS = Object.fromEntries(
  Object.entries(MASCOT_SPRITES).map(([mascot, rows]) => [mascot, blinkOf(rows)]),
) as Record<Mascot, Blink>;
