import type { Pixie, TeamMember } from "../../api/types.ts";
import { fourFaces } from "./motion.ts";
import { Sprite } from "./Sprite.tsx";

interface Props {
  members: readonly TeamMember[];
  pixies: Record<string, Pixie>;
  className: string;
  // Each sprite's width in pixels.
  size: number;
}

/**
 * A team's mark (B48): its members' sprites in a grid of four, the leader first; each
 * hops while its call runs. Members no longer known are left out before the cells fill.
 */
export function TeamFace({ members, pixies, className, size }: Props) {
  const known = members.flatMap((member) => {
    const pixie = pixies[member.pixie_id];
    return pixie === undefined ? [] : [{ ...member, pixie }];
  });
  return (
    <span className={className} aria-hidden="true">
      {fourFaces(known).map(({ pixie, ...member }, cell) => {
        return (
          <Sprite
            key={cell}
            mascot={pixie.mascot}
            color={pixie.color}
            size={size}
            working={member.state === "running"}
            // A member shown twice still hops apart from itself.
            phaseKey={`${pixie.id}#${String(cell)}`}
          />
        );
      })}
    </span>
  );
}
