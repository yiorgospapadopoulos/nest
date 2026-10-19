import { MASCOT_INK, MASCOT_TONES } from "../../generated/mascots.ts";

/** How one sprite cell is filled. */
export interface Tone {
  fill: string;
  opacity: number;
}

/** `color` moved `amount` (0 to 1) of the way to `toward`, per RGB channel and rounded (B89). */
export function mix(color: string, toward: string, amount: number): string {
  const mixed = [1, 3, 5].map((at) => {
    const from = parseInt(color.slice(at, at + 2), 16);
    const to = parseInt(toward.slice(at, at + 2), 16);
    return Math.round(from + (to - from) * amount)
      .toString(16)
      .padStart(2, "0");
  });
  return `#${mixed.join("").toUpperCase()}`;
}

// The cell codes whose tone derives from the pixie's colour (design/mascots.toml).
const DERIVED: Partial<Record<string, (typeof MASCOT_TONES)[keyof typeof MASCOT_TONES]>> = {
  "+": MASCOT_TONES.shade,
  o: MASCOT_TONES.light,
  "*": MASCOT_TONES.wing,
};

/** How a sprite cell is drawn for a pixie of `color`, or null when the cell is empty. */
export function toneOf(code: string, color: string): Tone | null {
  if (code === "#") return { fill: color, opacity: 1 };
  if (code === "e" || code === "k") return { fill: MASCOT_INK, opacity: 1 };
  const derived = DERIVED[code];
  return derived === undefined
    ? null
    : { fill: mix(color, derived.toward, derived.amount), opacity: derived.opacity };
}
