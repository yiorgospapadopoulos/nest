// The Pixies list's order and teams (B40), as NestKit's PixieListLayout and PixiesStore:
// teams in their order with their members, then the pixies with no team; drag and drop,
// Move Up and Move Down change the one order of every pixie.
import type { Pixie, PixieTeam } from "../../api/types.ts";

/** A team in the list, with its listed members in pixie order. */
export interface TeamSection {
  team: PixieTeam;
  members: Pixie[];
}

export interface ListSections {
  teams: TeamSection[];
  // Pixies with no team, or one not known yet.
  loose: Pixie[];
}

const byPosition = <T extends { position: number; id: string }>(a: T, b: T) =>
  a.position - b.position || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

/** The pixies the list shows, in pixie order: the visible ones, or all while hidden ones show. */
export function listedPixies(pixies: Record<string, Pixie>, showsHidden: boolean): Pixie[] {
  return Object.values(pixies)
    .filter((p) => showsHidden || !p.hidden)
    .sort(byPosition);
}

/** `listed` are the pixies the list shows, in pixie order. */
export function listSections(listed: Pixie[], teams: PixieTeam[]): ListSections {
  const ordered = [...teams].sort(byPosition);
  const known = new Set(ordered.map((t) => t.id));
  return {
    teams: ordered.map((team) => ({
      team,
      members: listed.filter((p) => p.team_id === team.id),
    })),
    loose: listed.filter((p) => p.team_id === null || !known.has(p.team_id)),
  };
}

/** The ids of the pixies in the same section as this one, in order: Move Up and Down stay in it. */
export function neighbors(sections: ListSections, id: string): string[] {
  const lists = [...sections.teams.map((s) => s.members), sections.loose];
  return lists.find((list) => list.some((p) => p.id === id))?.map((p) => p.id) ?? [];
}

/**
 * The order with `id` where `target` is: below it when moved down, above it when moved
 * up. Null when there is nothing to send.
 */
export function movedOnto(order: string[], id: string, target: string): string[] | null {
  const from = order.indexOf(id);
  const to = order.indexOf(target);
  if (id === target || from === -1 || to === -1) return null;
  const next = order.filter((each) => each !== id);
  next.splice(to, 0, id);
  return next;
}

/** Move Up (-1) and Move Down (1) among the listed pixies of its section. */
export function movedBy(
  order: string[],
  id: string,
  offset: -1 | 1,
  listed: string[],
): string[] | null {
  const index = listed.indexOf(id);
  const target = index === -1 ? undefined : listed[index + offset];
  return target === undefined ? null : movedOnto(order, id, target);
}

/**
 * A pixie dropped on another: it joins the other's team (or leaves its own, `team` null)
 * when they differ, then takes the other's place. `pixies` are all of them, in order.
 */
export function placement(
  pixies: Pixie[],
  id: string,
  target: string,
): { team?: string | null; order: string[] | null } | null {
  const pixie = pixies.find((p) => p.id === id);
  const other = pixies.find((p) => p.id === target);
  if (pixie === undefined || other === undefined) return null;
  const order = movedOnto(
    pixies.map((p) => p.id),
    id,
    target,
  );
  return pixie.team_id === other.team_id ? { order } : { team: other.team_id, order };
}

/** A pixie dragged down the list lands below the one under the pointer, else above it. */
export function dropsBelow(dragged: Pixie, under: Pixie): boolean {
  return dragged.position < under.position;
}
