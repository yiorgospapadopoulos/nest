import type { Artifact, ArtifactFilter, ArtifactKind, Session } from "../../api/types.ts";
import type { IconName } from "../../ui/Icon.tsx";

export const KIND_LABELS: Record<ArtifactKind, string> = { markdown: "Markdown", html: "HTML" };
export const KIND_ICONS: Record<ArtifactKind, IconName> = { markdown: "doc", html: "code" };

/** One choice of the history's switch: which artifacts it lists. */
export interface ArtifactScope {
  label: string;
  filter: ArtifactFilter;
}

// The switch always has a first choice.
export type Scopes = [ArtifactScope, ...ArtifactScope[]];

const ALL: ArtifactScope = { label: "All", filter: {} };

/**
 * A chat's history: its own artifacts first, then its project's (a pixie's, for a habit
 * run), then every project's. A pixie's own chat lists what its page lists.
 */
export function chatScopes(session: Session): Scopes {
  const chat = { label: "This chat", filter: { session_id: session.id } };
  if (session.pixie_id == null) {
    return [chat, { label: "This project", filter: { repo: session.repo } }, ALL];
  }
  const pixie = pixieScopes(session.pixie_id);
  return session.habit_run_id == null ? pixie : [chat, ...pixie];
}

export function pixieScopes(pixieId: string): Scopes {
  return [{ label: "This pixie", filter: { pixie_id: pixieId } }, ALL];
}

/** The chat or pixie that saved it. */
export function originOf(artifact: Artifact): string {
  if (artifact.pixie_id !== null) return artifact.pixie_name ?? "A pixie";
  if (artifact.chat_deleted) return "Deleted chat";
  return artifact.chat_title ?? "A chat";
}
