import { useCallback, useEffect, useRef, useState } from "react";
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

// Not asked for yet (undefined), loading (null), failed, or loaded.
type DiffState = SessionDiff | null | "failed" | undefined;

/** The session's diff, loaded on demand; only the latest request's answer is kept. */
function useDiff(sessionId: string) {
  const { actions } = useStore();
  const [diff, setDiff] = useState<DiffState>(undefined);
  const latest = useRef(0);
  const loadDiff = useCallback(async () => {
    latest.current += 1;
    const request = latest.current;
    setDiff(null);
    const loaded = await actions.diff(sessionId);
    if (request === latest.current) setDiff(loaded ?? "failed");
  }, [actions, sessionId]);
  return { diff, loadDiff };
}

export function useReview(approval: Approval, session: Session | undefined) {
  const { actions } = useStore();
  const { busy, run } = useBusy();
  const { diff, loadDiff } = useDiff(approval.session_id);
  // The agent changed git refs itself: publishing waits until the user says they checked.
  const [acknowledged, setAcknowledged] = useState(false);
  // Reject asks first, from a button or a swipe.
  const [rejecting, setRejecting] = useState(false);
  // Publishing waits for the push address to be confirmed, with the message it was for.
  const [remote, setRemote] = useState<(RemotePrompt & { message: string }) | null>(null);
  const view = reviewOf(approval);
  const inPlace = session?.mode === "in_place";
  const violation = session?.git_violation === true;
  const publish = (message: string, confirmUrl?: string) =>
    run(async () => {
      const result = await actions.approveReview(approval, {
        ...body(message.trim() || approval.title),
        ...(confirmUrl === undefined ? {} : { confirm_remote_url: confirmUrl }),
      });
      if (typeof result === "object") setRemote({ ...result.remote, message });
      // Refused: show the branch as it is now, with any commits harness did not make.
      if (result === "refused" || typeof result === "object") void loadDiff();
      return result === "approved";
    });
  const body = (message: string): ApproveBody => ({
    commit_message: message,
    // In-place work is pushed without a pull request, committing only the changed files.
    ...(inPlace ? { files: view.paths, open_pr: false } : {}),
    ...(violation && acknowledged ? { acknowledge_violation: true } : {}),
    // Seen in the diff: publish that HEAD only, or be told it moved.
    ...(typeof diff === "object" && diff?.head.commit ? { expected_head: diff.head.commit } : {}),
  });
  return {
    view,
    busy,
    inPlace,
    violation,
    acknowledged,
    setAcknowledged,
    // Approving would be refused until the violation is acknowledged.
    blocked: violation && !acknowledged,
    title: session?.title ?? approval.title,
    approveLabel: inPlace ? "Approve and push" : "Approve and open PR",
    diff,
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
    rejecting,
    askReject: () => {
      setRejecting(true);
    },
    cancelReject: () => {
      setRejecting(false);
    },
    reject: () => {
      setRejecting(false);
      return run(() => actions.rejectReview(approval));
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
