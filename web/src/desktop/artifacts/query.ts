// Which artifacts the Artifacts view lists, as NestKit's ArtifactQuery and ArtifactScope
// (ArtifactsStore.swift), over the store's lists.
import type { Artifact, ArtifactFilter, Pixie, Session } from "../../api/types.ts";
import { artifactList, filterKey } from "../../store/artifacts.ts";
import type { State } from "../../store/state.ts";

export type ArtifactQuery =
  // The ones a chat saved.
  | { chat: string }
  // Every chat's of a project, deleted chats' too.
  | { project: string }
  // The ones a pixie's chat and habit runs saved.
  | { pixie: string }
  // Every pixie's.
  | { pixies: true };

/** The focused chat's or pixie's (`narrow`) with a switch to the wider list. */
export interface ArtifactScope {
  narrow: ArtifactQuery | null;
  wide: ArtifactQuery;
}

/** The artifact and version the reader shows. */
export interface ArtifactSelection {
  id: string;
  version: number;
}

/** The daemon's filter; every pixie's comes from the unfiltered list. */
export function filterOf(query: ArtifactQuery): ArtifactFilter {
  if ("chat" in query) return { session_id: query.chat };
  if ("project" in query) return { repo: query.project };
  if ("pixie" in query) return { pixie_id: query.pixie };
  return {};
}

export function matches(query: ArtifactQuery, artifact: Artifact): boolean {
  if ("chat" in query) return artifact.session_id === query.chat;
  if ("project" in query) return artifact.repo === query.project;
  if ("pixie" in query) return artifact.pixie_id === query.pixie;
  return artifact.pixie_id !== null;
}

/** The same key for the same query. */
export function queryKey(query: ArtifactQuery): string {
  return "pixies" in query ? "pixies" : filterKey(filterOf(query));
}

/** The scope switch's label. */
export function queryLabel(query: ArtifactQuery): string {
  if ("chat" in query) return "This chat";
  if ("project" in query) return "Whole project";
  if ("pixie" in query) return "This pixie";
  return "All pixies";
}

/** What the list says when the scope holds none. */
export function emptyText(query: ArtifactQuery): string {
  if ("chat" in query) return "This chat has saved no artifacts yet.";
  if ("project" in query) return "No chat in this project has saved an artifact yet.";
  if ("pixie" in query) return "This pixie has saved no artifacts yet.";
  return "No pixie has saved an artifact yet.";
}

/** The query's artifacts newest first, or null until it is loaded. */
export function listed(state: State, query: ArtifactQuery): Artifact[] | null {
  return artifactList(state, filterOf(query))?.filter((found) => matches(query, found)) ?? null;
}

interface Focus {
  // The project shown, or null in the Pixies tab.
  project: string | null;
  // The focused pane.
  focused: string | null;
  sessions: Record<string, Session>;
  pixies: Record<string, Pixie>;
}

/**
 * In the Pixies tab the focused pixie's, with a switch to every pixie's; in a project the
 * focused chat's, with a switch to the whole project, or the whole project while no chat
 * is focused (Shell.artifactScope).
 */
export function artifactScope({ project, focused, sessions, pixies }: Focus): ArtifactScope {
  if (project === null) {
    return {
      narrow: focused !== null && focused in pixies ? { pixie: focused } : null,
      wide: { pixies: true },
    };
  }
  return {
    narrow: focused !== null && focused in sessions ? { chat: focused } : null,
    wide: { project },
  };
}

/** A selection the list lacks, or none, moves to its newest artifact at its latest version. */
export function keptSelection(
  list: Artifact[],
  selection: ArtifactSelection | null,
): ArtifactSelection | null {
  if (selection !== null && list.some((found) => found.id === selection.id)) return selection;
  const newest = list[0];
  return newest === undefined ? null : { id: newest.id, version: newest.latest_version };
}
