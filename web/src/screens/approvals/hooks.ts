import { useState } from "react";
import { mergeOf, permissionOf, planOf, reviewOf } from "../../api/payloads.ts";
import type { Approval, ApproveBody, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";

/** Where the session's agent works; tool paths inside it are shown relative to it. */
export function workRoot(session: Session | undefined): string | null {
  return session?.worktree_path ?? session?.cwd ?? null;
}

/** Runs one resolving action at a time; the card goes away when it succeeds. */
function useBusy() {
  const [busy, setBusy] = useState(false);
  const run = async (action: () => Promise<boolean>) => {
    setBusy(true);
    if (!(await action())) setBusy(false);
  };
  return { busy, run };
}

export function usePermission(approval: Approval, session: Session | undefined) {
  const { actions } = useStore();
  const { busy, run } = useBusy();
  const view = permissionOf(approval, workRoot(session));
  const decide = (behavior: "allow" | "deny", always = false) => {
    const done =
      behavior === "deny"
        ? "Rejected. Claude continues without it"
        : always
          ? `Always allowed: ${view.tool}`
          : `Approved: ${view.command}`;
    return run(() => actions.resolve(approval, { behavior, always }, done));
  };
  return { view, busy, decide };
}

export function usePlan(approval: Approval) {
  const { actions } = useStore();
  const { busy, run } = useBusy();
  return {
    busy,
    plan: planOf(approval),
    // Claude then continues with Accept edits, as in Claude Code.
    approve: () => run(() => actions.resolve(approval, { decision: "approve" }, "Plan approved")),
    keepPlanning: (note: string) =>
      run(() =>
        actions.resolve(
          approval,
          { decision: "keep_planning", message: note.trim() || null },
          "Claude keeps planning",
        ),
      ),
  };
}

export function useReview(approval: Approval, session: Session | undefined) {
  const { actions } = useStore();
  const { busy, run } = useBusy();
  const view = reviewOf(approval);
  const inPlace = session?.mode === "in_place";
  const body = (message: string): ApproveBody =>
    // In-place work is pushed without a pull request, committing only the changed files.
    inPlace
      ? { commit_message: message, files: view.paths, open_pr: false }
      : { commit_message: message };
  return {
    view,
    busy,
    title: session?.title ?? approval.title,
    approveLabel: inPlace ? "Approve and push" : "Approve and open PR",
    approve: (message: string) =>
      run(() => actions.approveReview(approval, body(message.trim() || approval.title))),
    reject: () => run(() => actions.rejectReview(approval)),
    feedback: (text: string) => run(() => actions.feedback(approval, text)),
  };
}

export function useMerge(approval: Approval) {
  const { actions } = useStore();
  const { busy, run } = useBusy();
  const view = mergeOf(approval);
  return { view, busy, merge: () => run(() => actions.merge(approval, view.number)) };
}

/** "Send to agent" for failed checks; the card goes away once the agent starts. */
export function useCiFailure(session: Session, names: string[]) {
  const { actions } = useStore();
  const { busy, run } = useBusy();
  return { busy, send: () => run(() => actions.sendCiFailure(session, names)) };
}

/** Interrupt or nudge a stuck chat; the card goes away once the turn ends. */
export function useStuck(sessionId: string, details: string) {
  const { actions } = useStore();
  const { busy, run } = useBusy();
  return {
    busy,
    interrupt: () => run(() => actions.interrupt(sessionId)),
    nudge: () => run(() => actions.nudge(sessionId, details)),
  };
}
