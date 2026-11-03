// The colours of a project's branches in the sidebar (B96), as the Mac's LaneColors: the
// default branch grey, the others in the palette's order, cycling once all are in use.
// The Mac assigns them from its branch map; here they follow the sidebar's order.

export const LANES = ["root", "violet", "teal", "blue", "pink", "lime", "orange", "yellow"];

/** Each branch's palette index, in the order the branches are first shown. */
export function laneIndices(branches: string[], defaultBranch: string | null): Map<string, number> {
  const assigned = new Map<string, number>();
  let next = 0;
  for (const branch of branches) {
    if (assigned.has(branch)) continue;
    if (branch === defaultBranch) {
      assigned.set(branch, 0);
      continue;
    }
    assigned.set(branch, (next % (LANES.length - 1)) + 1);
    next += 1;
  }
  return assigned;
}
