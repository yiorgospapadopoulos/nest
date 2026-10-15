import { Icon } from "../../ui/Icon.tsx";
import { placeName, type ChatPlace } from "./place.ts";

/** A list row's mark: the branch icon and the worktree's name or the folder's branch. */
export function PlaceMark({ place }: { place: ChatPlace | null }) {
  return (
    place !== null && (
      <span className="plm">
        <Icon name="branch" />
        <span>{placeName(place)}</span>
      </span>
    )
  );
}

/** The open chat's header chip, as the list row's mark, with the folder on hover. */
export function PlaceChip({ place }: { place: ChatPlace | null }) {
  if (place === null) return null;
  const worktree = place.kind === "worktree";
  const help = worktree
    ? `Worktree ${place.name}${place.folder === null ? "" : ` in ${place.folder}`}`
    : `${place.branch === null ? "In" : `On ${place.branch} in`} ${place.folder}`;
  const lead = worktree ? "Worktree " : place.branch === null ? "" : "On ";
  return (
    <span className="chip" title={help}>
      <Icon name="branch" />
      <span>
        {lead !== "" && <span className="sr">{lead}</span>}
        {placeName(place)}
      </span>
    </span>
  );
}
