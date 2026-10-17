import type { Artifact, ArtifactDetail, ArtifactFilter } from "../api/types.ts";
import type { State } from "./state.ts";

// The filters a list combines, in the order its key names them.
const FILTERS = ["repo", "session_id", "pixie_id"] as const;

/** The same key for the same filters, whatever order they were given in. */
export function filterKey(filter: ArtifactFilter): string {
  return FILTERS.map((name) => `${name}=${filter[name] ?? ""}`).join("&");
}

/** Whether a list of `filter` would hold the artifact, as the daemon's filters decide. */
export function matches(artifact: Artifact, filter: ArtifactFilter): boolean {
  return FILTERS.every((name) => filter[name] === undefined || artifact[name] === filter[name]);
}

/** The loaded list of `filter`, newest first; null until it loaded. */
export function artifactList(state: State, filter: ArtifactFilter): Artifact[] | null {
  const ids = state.artifactLists[filterKey(filter)]?.ids;
  if (ids === undefined) return null;
  return ids
    .map((id) => state.artifacts[id])
    .filter((found): found is Artifact => found !== undefined)
    .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
}

/** The artifact's fields alone: a detail's versions are fetched when they show. */
export function summaryOf(found: Artifact): Artifact {
  const summary: Artifact & Partial<Pick<ArtifactDetail, "versions">> = { ...found };
  delete summary.versions;
  return summary;
}

export function withList(state: State, filter: ArtifactFilter, artifacts: Artifact[]): State {
  const known = { ...state.artifacts };
  for (const artifact of artifacts) known[artifact.id] = artifact;
  return {
    ...state,
    artifacts: known,
    artifactLists: {
      ...state.artifactLists,
      [filterKey(filter)]: { filter, ids: artifacts.map((a) => a.id) },
    },
  };
}

/** The artifact's latest fields; a saved one also joins every loaded list it belongs in. */
export function withArtifact(state: State, artifact: Artifact, saved = false): State {
  const lists = saved
    ? Object.fromEntries(
        Object.entries(state.artifactLists).map(([key, list]) => [
          key,
          matches(artifact, list.filter) && !list.ids.includes(artifact.id)
            ? { ...list, ids: [...list.ids, artifact.id] }
            : list,
        ]),
      )
    : state.artifactLists;
  return {
    ...state,
    artifacts: { ...state.artifacts, [artifact.id]: summaryOf(artifact) },
    artifactLists: lists,
  };
}

export function withSeen(state: State, id: string): State {
  const known = state.artifacts[id];
  if (known === undefined || known.seen) return state;
  return { ...state, artifacts: { ...state.artifacts, [id]: { ...known, seen: true } } };
}

/** Deleted: out of every list, and known as gone for the cards that name it. */
export function withoutArtifact(state: State, id: string): State {
  return {
    ...state,
    artifacts: Object.fromEntries(Object.entries(state.artifacts).filter(([key]) => key !== id)),
    artifactLists: Object.fromEntries(
      Object.entries(state.artifactLists).map(([key, list]) => [
        key,
        { ...list, ids: list.ids.filter((each) => each !== id) },
      ]),
    ),
    artifactsGone: { ...state.artifactsGone, [id]: true },
  };
}

/** The chats of `field` `value` are gone; their artifacts stay, marked as from a deleted chat. */
export function withChatsDeleted(
  state: State,
  field: "session_id" | "pixie_id",
  value: string,
): State {
  const hit = Object.values(state.artifacts).filter((a) => a[field] === value && !a.chat_deleted);
  if (hit.length === 0) return state;
  const artifacts = { ...state.artifacts };
  for (const artifact of hit) artifacts[artifact.id] = { ...artifact, chat_deleted: true };
  return { ...state, artifacts };
}
