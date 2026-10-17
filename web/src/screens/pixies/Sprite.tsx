import type { CSSProperties } from "react";
import type { Mascot } from "../../api/types.ts";
import { MASCOT_SPRITES } from "../../generated/mascots.ts";
import { BLINKS, type Cell } from "./blink.ts";
import { phaseOffset, useReducedMotion } from "./motion.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";

interface Props {
  mascot: Mascot;
  color: string;
  // Width in pixels; the grid is 12 by 10 cells.
  size: number;
  // The pixie is at work: the sprite hops and blinks (B48), unless Reduce Motion is on.
  working?: boolean;
  // Sets where in its cycle the sprite starts, such as the pixie's id.
  phaseKey?: string;
}

/**
 * A pixie's mascot: one square per filled cell of its pixel grid, in the pixie's colour.
 * At work it hops a cell up and blinks on the stylesheet's step keyframes, drawing the
 * hop above its box so nothing around it moves.
 */
export function Sprite({ mascot, color, size, working = false, phaseKey = "" }: Props) {
  const reduced = useReducedMotion();
  const moving = working && !reduced;
  const rows = MASCOT_SPRITES[mascot];
  const blink = BLINKS[mascot];
  const eyes = blink.mode === "hide" ? blink.cells : [];
  const isEye = (x: number, y: number) => eyes.some(([ex, ey]) => ex === x && ey === y);
  const square = ([x, y]: Cell) => (
    <rect key={`${String(x)}-${String(y)}`} x={x} y={y} width={1} height={1} fill={color} />
  );
  const body = rows.flatMap((row, y) =>
    Array.from({ length: row.length }, (_, x) =>
      row.charAt(x) === "#" && !isEye(x, y) ? square([x, y]) : null,
    ),
  );
  return (
    <svg
      className={moving ? "pxs pxwork" : "pxs"}
      style={
        moving ? ({ "--pxph": `-${String(phaseOffset(phaseKey))}ms` } as CSSProperties) : undefined
      }
      role="img"
      aria-label={mascot}
      width={size}
      height={(size * 10) / 12}
      viewBox="0 0 12 10"
      overflow="visible"
      shapeRendering="crispEdges"
    >
      <g className="pxhop">
        {body}
        {eyes.length > 0 && <g className="pxeye">{eyes.map(square)}</g>}
        {moving && blink.mode === "fill" && <g className="pxlid">{blink.cells.map(square)}</g>}
      </g>
    </svg>
  );
}

/**
 * Still fireflies for a sprite that stays still under Reduce Motion (B48, B80); nothing
 * otherwise, as the sprite's hop shows the work.
 */
export function WorkingDot({ working }: { working: boolean }) {
  const reduced = useReducedMotion();
  return working && reduced ? <Fireflies size={9} /> : null;
}
