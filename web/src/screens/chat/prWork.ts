// What the pull request details show of the deeper pull request work (B149), on both
// layouts: merge when checks pass, the chat under a stacked chat, moving its branch, a new
// chat on top, and the review guide.
import type { RestackView } from "../../api/payloads.ts";
import type { PrStatus, Session } from "../../api/types.ts";
import { shownTitle, supportsFeature } from "../../store/selectors.ts";
import type { State } from "../../store/state.ts";

export const MERGE_WHEN_READY = "Merge when checks pass";

/** On while Nest waits to merge, or while GitHub's own auto-merge is on. */
export function mergesWhenReady(session: Session): boolean {
  return session.merge_when_ready != null || session.pr?.auto_merge != null;
}

/** Who merges it, while the switch is on; nothing while it is off. */
export function mergeWhenReadyLine(session: Session): string | null {
  if (!mergesWhenReady(session)) return null;
  return session.pr?.auto_merge != null
    ? "GitHub merges it when checks pass"
    : "Nest merges it when checks pass, while Nest is running";
}

export interface RestackAction {
  label: "Push" | "Rebase and push" | "Rebase";
  // The toast once it is done.
  done: string;
}

/** The one button for a branch that has to move: what is left of rebasing and pushing. */
export function restackAction(rebased: boolean, hasPr: boolean): RestackAction {
  if (!hasPr) return { label: "Rebase", done: "Rebased" };
  return rebased
    ? { label: "Push", done: "Pushed" }
    : { label: "Rebase and push", done: "Rebased and pushed" };
}

/** A restack card's title: "#12 wip moved onto main", or "Move wip onto main" before the rebase. */
export function restackTitle({ branch, base, rebased, number }: RestackView): string {
  const name = branch ?? "the branch";
  if (!rebased) return `Move ${name} onto ${base}`;
  return `${number === null ? "" : `#${String(number)} `}${name} moved onto ${base}`;
}

export interface StackParent {
  // The chat to open; null when it is not known here.
  id: string | null;
  text: string;
}

/** "On top of #12", or the chat's name while it has no pull request; null when not stacked. */
export function stackParent(state: State, session: Session): StackParent | null {
  const stack = session.stack ?? null;
  if (stack?.parent == null) return null;
  const parent = state.sessions[stack.parent];
  if (parent === undefined) {
    return stack.parent_branch === null
      ? null
      : { id: null, text: `On top of ${stack.parent_branch}` };
  }
  const name = parent.pr === null ? shownTitle(parent) : `#${String(parent.pr.number)}`;
  return { id: parent.id, text: `On top of ${name}` };
}

/** The branch a new chat on top of this one starts from; null outside a worktree. */
export function onTopBranch(session: Session): string | null {
  const worktree = session.mode === "worktree" || session.worktree_path !== null;
  return worktree ? session.branch : null;
}

/**
 * Whether the details offer a review guide: while the pull request is open, or once one was
 * written, and only on an engine that can write it with every tool off.
 */
export function offersGuide(state: State, session: Session, pr: PrStatus | null): boolean {
  if (pr === null || !supportsFeature(state, "review_guide", session.provider)) return false;
  return pr.state === "open" || session.pr_guide != null;
}

export type GuideView =
  | { kind: "none" }
  | { kind: "writing" }
  | { kind: "failed"; error: string }
  | {
      kind: "ready";
      artifactId: string | null;
      commentUrl: string | null;
      // Written for an older head of the pull request.
      stale: boolean;
    };

export function guideView(session: Session, pr: PrStatus | null): GuideView {
  const guide = session.pr_guide ?? null;
  if (guide === null) return { kind: "none" };
  switch (guide.state) {
    case "writing":
      return { kind: "writing" };
    case "failed":
      return { kind: "failed", error: guide.error ?? "The guide could not be written" };
    case "ready":
      return {
        kind: "ready",
        artifactId: guide.artifact_id,
        commentUrl: guide.comment_url,
        stale: pr !== null && guide.head_sha !== pr.head_sha,
      };
  }
}
