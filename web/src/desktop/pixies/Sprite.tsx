import type { CSSProperties } from "react";
import type { Mascot, Pixie, TeamMember } from "../../api/types.ts";
import { MASCOT_SPRITES } from "../../generated/mascots.ts";
import { fourFaces, phaseOffset, useReducedMotion } from "../../screens/pixies/motion.ts";
import { toneOf } from "../../screens/pixies/tones.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";

// The desktop's own drawing of a pixie, the same as the phone's and the Mac's Sprite.swift.

interface Props {
  mascot: Mascot;
  color: string;
  // Width and height in pixels; the grid is 14 by 14 cells.
  size: number;
  // The pixie is at work: the sprite hops and blinks (B48), unless Reduce Motion is on.
  working?: boolean;
  // Sets where in its cycle the sprite starts, such as the pixie's id.
  phaseKey?: string;
  // Blinks now and then while it sits still, as the pill's idle Nightshade (B117).
  blink?: boolean;
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
export function Sprite({
  mascot,
  color,
  size,
  working = false,
  phaseKey = "",
  blink = false,
}: Props) {
  const reduced = useReducedMotion();
  const moving = working && !reduced;
  const blinking = blink && !moving && !reduced;
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
      className={moving ? "pxs pxwork" : blinking ? "pxs pxblinks" : "pxs"}
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
        {(moving || blinking) && <g className="pxlid">{lids}</g>}
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

interface TeamFaceProps {
  members: readonly TeamMember[];
  pixies: Record<string, Pixie>;
  className: string;
  // Each sprite's width in pixels.
  size: number;
  // All hop, or none, whatever each member's call does (the pill, as the Mac's island).
  working?: boolean;
}

/**
 * A team's mark (B48): its members' sprites in a grid of four, the leader first; each
 * hops while its call runs. Members no longer known are left out before the cells fill.
 */
export function TeamFace({ members, pixies, className, size, working }: TeamFaceProps) {
  const known = members.flatMap((member) => {
    const pixie = pixies[member.pixie_id];
    return pixie === undefined ? [] : [{ ...member, pixie }];
  });
  return (
    <span className={className} aria-hidden="true">
      {fourFaces(known).map(({ pixie, ...member }, cell) => (
        <Sprite
          key={cell}
          mascot={pixie.mascot}
          color={pixie.color}
          size={size}
          working={working ?? member.state === "running"}
          // A member shown twice still hops apart from itself.
          phaseKey={`${pixie.id}#${String(cell)}`}
        />
      ))}
    </span>
  );
}
