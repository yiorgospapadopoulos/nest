import { useCallback, useEffect, useMemo, useState } from "react";
import { mergeOf, permissionOf, planOf, reviewOf } from "../../api/payloads.ts";
import type { Approval, ApproveBody, PlanMode, Session, SessionDiff } from "../../api/types.ts";
import type { RemotePrompt } from "../../store/actions.ts";
import { useStore } from "../../store/context.ts";
import { planModes } from "../chat/options.ts";

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
          ? `Always allowed: ${view.always}`
          : `Approved: ${view.command}`;
    return run(() => actions.resolve(approval, { behavior, always }, done));
  };
  return { view, busy, decide };
}

export function usePlan(approval: Approval) {
  const { state, actions } = useStore();
  const { busy, run } = useBusy();
  const unknownModels = state.models === null;
  // Whether Auto is offered depends on the chat's model.
  useEffect(() => {
    if (unknownModels) void actions.loadChoices();
  }, [unknownModels, actions]);
  const model = state.sessions[approval.session_id]?.model ?? null;
  return {
    busy,
    plan: planOf(approval),
    modes: planModes(state.models, model),
    // Claude then goes on in `mode`; Accept edits unless chosen otherwise, as in Claude Code.
    approve: (mode: PlanMode) =>
      run(() => actions.resolve(approval, { decision: "approve", mode }, "Plan approved")),
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

interface DiffAnswer {
  // The request it answers.
  request: object | null;
  diff: SessionDiff | null;
  failed: boolean;
}

/**
 * The session's diff, loaded when the approval is shown, again whenever the approval or the
 * session changes, and on request. Only the latest request's answer is kept; the previous
 * diff stays on screen while it loads, and a failed load drops it.
 */
function useDiff(approval: Approval, session: Session | undefined) {
  const { actions } = useStore();
  const [reloads, setReloads] = useState(0);
  const request = useMemo(() => ({ approval, session, reloads }), [approval, session, reloads]);
  const [answer, setAnswer] = useState<DiffAnswer>({ request: null, diff: null, failed: false });
  useEffect(() => {
    let current = true;
    void actions.diff(approval.session_id).then((diff) => {
      if (current) setAnswer({ request, diff, failed: diff === null });
    });
    return () => {
      current = false;
    };
  }, [actions, approval.session_id, request]);
  const loadDiff = useCallback(() => {
    setReloads((n) => n + 1);
  }, []);
  return {
    diff: answer.diff,
    loading: answer.request !== request,
    failed: answer.failed,
    loadDiff,
  };
}

export function useReview(approval: Approval, session: Session | undefined) {
  const { actions } = useStore();
  const { busy, run } = useBusy();
  const { diff, loading, failed, loadDiff } = useDiff(approval, session);
  // Publishing waits for the push address to be confirmed, with the message it was for.
  const [remote, setRemote] = useState<(RemotePrompt & { message: string }) | null>(null);
  const view = reviewOf(approval);
  const inPlace = session?.mode === "in_place";
  // Only a worktree chat without a pull request yet pushes (and opens one); the others
  // commit and leave pushing to the user (B56).
  const commitOnly = inPlace || session?.pr_url != null;
  // Approving sends what the user saw, so it waits for the diff, and for any reload of it.
  const ready = diff !== null && !loading;
  const publish = async (message: string, confirmUrl?: string) => {
    // A swipe can come before the diff has loaded: nothing to publish yet.
    if (diff === null || loading) return;
    await run(async () => {
      const result = await actions.approveReview(
        approval,
        {
          ...body(diff, message.trim() || approval.title),
          ...(confirmUrl === undefined ? {} : { confirm_remote_url: confirmUrl }),
        },
        approved(diff),
      );
      if (typeof result === "object") setRemote({ ...result.remote, message });
      // Refused: show the branch as it is now.
      if (result === "refused" || typeof result === "object") loadDiff();
      return result === "approved";
    });
  };
  // What the toast says once approved.
  const approved = (seen: SessionDiff): string => {
    if (!commitOnly) return "Pull request opened";
    return seen.head.branch === null
      ? "Committed, not pushed"
      : `Committed to ${seen.head.branch}, not pushed`;
  };
  const body = (seen: SessionDiff, message: string): ApproveBody => ({
    commit_message: message,
    // In-place work commits only the changed files.
    ...(inPlace ? { files: view.paths } : {}),
    ...(commitOnly ? { open_pr: false, push: false } : {}),
    // Publish exactly what was reviewed, or be told it changed.
    expected_fingerprint: seen.fingerprint,
    ...(seen.head.commit === null ? {} : { expected_head: seen.head.commit }),
  });
  return {
    view,
    busy,
    commitOnly,
    ready,
    title: session?.title ?? approval.title,
    approveLabel: commitOnly ? "Approve and commit" : "Approve and open PR",
    diff,
    diffFailed: failed,
    loadDiff,
    approve: (message: string) => publish(message),
    remote,
    cancelRemote: () => {
      setRemote(null);
    },
    // Approves again with the same message, pushing to the one address origin has now.
    pushThere: (message: string, url: string) => {
      setRemote(null);
      return publish(message, url);
    },
    feedback: (text: string) => run(() => actions.feedback(approval, text)),
  };
}

export type Review = ReturnType<typeof useReview>;

export function useMerge(approval: Approval) {
  const { actions } = useStore();
  const { busy, run } = useBusy();
  const view = mergeOf(approval);
  return { view, busy, merge: () => run(() => actions.merge(approval, view.number)) };
}

/** "Send to agent" for failed checks; the card goes away once the agent starts. */
export function useCiFailure(session: Session) {
  const { actions } = useStore();
  const { busy, run } = useBusy();
  return { busy, send: () => run(() => actions.sendCiFailure(session)) };
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
