import type { CSSProperties } from "react";
import type { Mascot } from "../../api/types.ts";
import { MASCOT_SPRITES } from "../../generated/mascots.ts";
import { phaseOffset, useReducedMotion } from "./motion.ts";
import { toneOf } from "./tones.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";

interface Props {
  mascot: Mascot;
  color: string;
  // Width and height in pixels; the grid is 14 by 14 cells.
  size: number;
  // The pixie is at work: the sprite hops and blinks (B48), unless Reduce Motion is on.
  working?: boolean;
  // Sets where in its cycle the sprite starts, such as the pixie's id.
  phaseKey?: string;
}

// A row's run of cells of one code, drawn as one rect so no seams show between them.
interface Run {
  x: number;
  y: number;
  width: number;
  code: string;
}

function runsOf(rows: readonly string[]): Run[] {
  return rows.flatMap((row, y) => {
    const runs: Run[] = [];
    for (let x = 0; x < row.length; x++) {
      const code = row.charAt(x);
      const last = runs.at(-1);
      if (last?.code === code) last.width++;
      else runs.push({ x, y, width: 1, code });
    }
    return runs;
  });
}

/**
 * A pixie's mascot: its pixel grid, each cell in its tone of the pixie's colour (B89).
 * At work it hops a cell up and blinks on the stylesheet's step keyframes, drawing the
 * hop above its box so nothing around it moves; a blink covers the eyes in the body colour.
 */
export function Sprite({ mascot, color, size, working = false, phaseKey = "" }: Props) {
  const reduced = useReducedMotion();
  const moving = working && !reduced;
  const runs = runsOf(MASCOT_SPRITES[mascot]);
  const rect = ({ x, y, width }: Run, fill: string, opacity: number) => (
    <rect
      key={`${String(x)}-${String(y)}`}
      x={x}
      y={y}
      width={width}
      height={1}
      fill={fill}
      fillOpacity={opacity < 1 ? opacity : undefined}
    />
  );
  const cells = runs.flatMap((run) => {
    const tone = toneOf(run.code, color);
    return tone === null ? [] : [rect(run, tone.fill, tone.opacity)];
  });
  const lids = runs.filter((run) => run.code === "e").map((run) => rect(run, color, 1));
  return (
    <svg
      className={moving ? "pxs pxwork" : "pxs"}
      style={
        moving ? ({ "--pxph": `-${String(phaseOffset(phaseKey))}ms` } as CSSProperties) : undefined
      }
      role="img"
      aria-label={mascot}
      width={size}
      height={size}
      viewBox="0 0 14 14"
      overflow="visible"
      shapeRendering="crispEdges"
    >
      <g className="pxhop">
        {cells}
        {moving && <g className="pxlid">{lids}</g>}
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
