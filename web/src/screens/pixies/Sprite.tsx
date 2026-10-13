import type { Mascot } from "../../api/types.ts";
import { MASCOT_SPRITES } from "../../generated/mascots.ts";

interface Props {
  mascot: Mascot;
  color: string;
  // Width in pixels; the grid is 12 by 10 cells.
  size: number;
}

/** A pixie's mascot: one square per filled cell of its pixel grid, in the pixie's colour. */
export function Sprite({ mascot, color, size }: Props) {
  const rows = MASCOT_SPRITES[mascot];
  return (
    <svg
      className="pxs"
      role="img"
      aria-label={mascot}
      width={size}
      height={(size * 10) / 12}
      viewBox="0 0 12 10"
      shapeRendering="crispEdges"
    >
      {rows.flatMap((row, y) =>
        Array.from({ length: row.length }, (_, x) =>
          row.charAt(x) === "#" ? (
            <rect key={`${String(x)}-${String(y)}`} x={x} y={y} width={1} height={1} fill={color} />
          ) : null,
        ),
      )}
    </svg>
  );
}
