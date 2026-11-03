// Approving a review, as NestKit's PublishForm and PublishProgress: what the approve sheet
// edits and sends, and each git step's progress from the daemon's events. A worktree chat
// without a pull request pushes to open one (B56); one whose pull request is open pushes
// to it, unless the user chose Approve and commit (B101); otherwise Approve commits and
// never pushes.
import { reviewOf } from "../../api/payloads.ts";
import { ApiError } from "../../api/client.ts";
import type {
  Approval,
  ApproveBody,
  NestEvent,
  Session,
  SessionDiff,
  SessionMode,
} from "../../api/types.ts";
import { COMMIT_TITLE, openPullRequest, replyNote } from "../../screens/approvals/hooks.ts";

export interface PublishForm {
  commitMessage: string;
  openPR: boolean;
  prTitle: string;
  prBody: string;
  // The push address the user confirmed after approving was refused for it (I-008).
  confirmRemoteUrl: string | null;
  mode: SessionMode;
  // The chat has a pull request, open or not.
  hasPullRequest: boolean;
  // The chat's open pull request, which Approve pushes to (B101).
  pullRequest: number | null;
  // With an open pull request: push to it, or only commit (Approve and commit).
  pushToPR: boolean;
  // In-place chats commit only the reviewed files.
  files: string[];
  // "Also replies on 2 review threads…", for a push to the open pull request.
  threadsNote: string | null;
}

/** Starts from the review's title as the commit message; `commitOnly` from Approve and commit. */
export function publishForm(
  approval: Approval,
  session: Session | undefined,
  commitOnly = false,
): PublishForm {
  return {
    commitMessage: approval.title,
    openPR: true,
    prTitle: "",
    prBody: "",
    confirmRemoteUrl: null,
    mode: session?.mode ?? "worktree",
    hasPullRequest: session?.pr_url != null,
    pullRequest: openPullRequest(session),
    pushToPR: !commitOnly,
    files: approval.kind === "review" ? reviewOf(approval).paths : [],
    threadsNote: replyNote(session),
  };
}

/** In place works on the checkout's own branch, and a chat with a pull request has one. */
export const canOpenPR = (form: PublishForm) => form.mode !== "in_place" && !form.hasPullRequest;

const opensPR = (form: PublishForm) => canOpenPR(form) && form.openPR;

export const pushesToPR = (form: PublishForm) => form.pullRequest !== null && form.pushToPR;

/** Approve pushes the branch, to open the pull request or update the open one. */
export const pushes = (form: PublishForm) => opensPR(form) || pushesToPR(form);

export const pushTitle = (number: number) => `Approve and push to #${String(number)}`;

/** The sheet's title and Approve button. */
export function formTitle(form: PublishForm): string {
  if (pushesToPR(form) && form.pullRequest !== null) return pushTitle(form.pullRequest);
  return opensPR(form) ? "Approve and open PR" : COMMIT_TITLE;
}

/** What Approve does with the pull request, when it opens none. */
export function formNote(form: PublishForm): string | null {
  if (form.mode === "in_place") {
    return "This chat works in the project folder, so its files are committed on the current branch, without pushing or a pull request.";
  }
  if (form.pullRequest !== null) {
    return form.pushToPR
      ? `Approve commits and pushes to the pull request's branch, updating #${String(form.pullRequest)}.`
      : "This chat's pull request is already open. Approve and commit commits to its branch without pushing; the pull request stays as it is.";
  }
  if (form.hasPullRequest) {
    return "This chat's pull request is no longer open. Approve commits to its branch without pushing.";
  }
  return null;
}

/** The grey line under the note while Approve pushes to the open pull request. */
export const formReplyNote = (form: PublishForm) => (pushesToPR(form) ? form.threadsNote : null);

/** The toast once approving went through. */
export function doneText(form: PublishForm, title: string): string {
  if (pushesToPR(form) && form.pullRequest !== null) {
    return `Pushed ${title} to #${String(form.pullRequest)}`;
  }
  return opensPR(form)
    ? `Opened a pull request for ${title}`
    : `Committed ${title} without pushing`;
}

export const canSubmit = (form: PublishForm) => form.commitMessage.trim() !== "";

export type StepKind = "commit" | "push" | "pr";

export const STEP_TITLES: Record<StepKind, string> = {
  commit: "Commit",
  push: "Push",
  pr: "Open pull request",
};

/** The steps the daemon will run, in order. */
export function steps(form: PublishForm): StepKind[] {
  if (opensPR(form)) return ["commit", "push", "pr"];
  return pushes(form) ? ["commit", "push"] : ["commit"];
}

/** What Approve sends, with the HEAD and fingerprint of the diff the user saw. */
export function approveBody(form: PublishForm, seen: SessionDiff): ApproveBody {
  const opens = opensPR(form);
  const push = pushes(form);
  const title = form.prTitle.trim();
  const body = form.prBody.trim();
  return {
    commit_message: form.commitMessage.trim(),
    ...(form.mode === "in_place" ? { files: form.files } : {}),
    push,
    open_pr: opens,
    ...(opens && title !== "" ? { pr_title: title } : {}),
    ...(opens && body !== "" ? { pr_body: body } : {}),
    ...(push && form.confirmRemoteUrl !== null
      ? { confirm_remote_url: form.confirmRemoteUrl }
      : {}),
    expected_fingerprint: seen.fingerprint,
    ...(seen.head.commit === null ? {} : { expected_head: seen.head.commit }),
  };
}

/** Where origin pushes now, from a refusal until the address is confirmed (D050). */
export interface PushRemote {
  urls: string[];
  // The address Nest recorded before, when origin changed since.
  confirmed: string | null;
}

/** The one address Push there confirms; none when origin pushes to several or none. */
export const remoteTarget = (remote: PushRemote) =>
  remote.urls.length === 1 ? (remote.urls[0] ?? null) : null;

export function remoteSummary(remote: PushRemote): string {
  if (remote.urls.length === 0) return "origin has no push address";
  if (remote.urls.length === 1) {
    return remote.confirmed === null ? "origin pushes to" : "origin now pushes to";
  }
  return "origin pushes to several addresses; fix the remote before pushing";
}

/** Why an approve call failed, as the sheet shows it. */
export interface PublishFailure {
  message: string;
  // 409: refused before any step ran.
  refused: boolean;
  // A git step's failure (502): its name and git's output.
  step: string | null;
  stderr: string;
  // What to do, beyond the daemon's words.
  hint: string | null;
  remote: PushRemote | null;
}

const HINTS: Readonly<Record<string, string>> = {
  head_changed: "The branch moved since you looked. Check the changes again.",
  review_changed: "The changes were read again. Check them before approving.",
};

const REMOTE_CODES: readonly string[] = ["remote_not_confirmed", "remote_changed"];

export function publishFailure(error: unknown): PublishFailure {
  if (!(error instanceof ApiError)) {
    return {
      message: error instanceof Error ? error.message : "Could not reach Nest",
      refused: false,
      step: null,
      stderr: "",
      hint: null,
      remote: null,
    };
  }
  const { data, code } = error;
  const refused = error.status === 409;
  const step = error.status === 502 && typeof data.step === "string" ? data.step : null;
  const urls = Array.isArray(data.remote_urls) ? data.remote_urls : [];
  return {
    message: error.message,
    refused,
    step,
    stderr: typeof data.stderr === "string" ? data.stderr : "",
    hint: refused && code !== null ? (HINTS[code] ?? null) : null,
    remote:
      refused && code !== null && REMOTE_CODES.includes(code)
        ? {
            urls: urls.filter((url): url is string => typeof url === "string"),
            confirmed: typeof data.confirmed_url === "string" ? data.confirmed_url : null,
          }
        : null,
  };
}

export type StepState = "pending" | "running" | "done" | "failed";

export interface PublishStep {
  kind: StepKind;
  state: StepState;
  // A failed step's output, or the failure's message.
  output: string;
}

/** The progress of one approve call, step by step. */
export interface PublishProgress {
  steps: PublishStep[];
  running: boolean;
  // Set when the call failed; the review stays pending and can be approved again.
  failure: PublishFailure | null;
}

const step = (kind: StepKind, state: StepState, output = ""): PublishStep => ({
  kind,
  state,
  output,
});

const markRunning = (list: PublishStep[], index: number) =>
  list.map((s, i) => (i === index ? step(s.kind, "running") : s));

/** A new run of these steps: the first one runs. */
export function startProgress(kinds: StepKind[]): PublishProgress {
  return {
    steps: markRunning(
      kinds.map((kind) => step(kind, "pending")),
      0,
    ),
    running: true,
    failure: null,
  };
}

const isStep = (name: string | null): name is StepKind =>
  name === "commit" || name === "push" || name === "pr";

/** A step's event: it and every step before it are done, and the next one runs. */
export function completeStep(progress: PublishProgress, kind: StepKind): PublishProgress {
  const index = progress.steps.findIndex((s) => s.kind === kind);
  if (index < 0) return progress;
  const done = progress.steps.map((s, i) => (i <= index ? step(s.kind, "done") : s));
  return { ...progress, steps: markRunning(done, index + 1) };
}

/** A failure: the steps before it went through, the ones after it wait. */
export function failStep(
  progress: PublishProgress,
  kind: string | null,
  message: string,
): PublishProgress {
  const named = isStep(kind) ? progress.steps.findIndex((s) => s.kind === kind) : -1;
  const running = progress.steps.findIndex((s) => s.state === "running");
  const index = named >= 0 ? named : running >= 0 ? running : 0;
  if (progress.steps.length === 0) return progress;
  return {
    ...progress,
    steps: progress.steps.map((s, i) =>
      i < index
        ? step(s.kind, "done")
        : i === index
          ? step(s.kind, "failed", message)
          : step(s.kind, "pending"),
    ),
  };
}

export function finishProgress(progress: PublishProgress): PublishProgress {
  return { steps: progress.steps.map((s) => step(s.kind, "done")), running: false, failure: null };
}

/** A refusal (409) ran no step: they stay pending and the failure says why. */
export function failProgress(progress: PublishProgress, failure: PublishFailure): PublishProgress {
  let next = progress;
  if (failure.refused) {
    next = { ...progress, steps: progress.steps.map((s) => step(s.kind, "pending")) };
  } else if (failure.step !== null) {
    const output = failure.stderr.trim();
    next = failStep(progress, failure.step, output === "" ? failure.message : output);
  } else if (!progress.steps.some((s) => s.state === "failed")) {
    next = failStep(progress, null, failure.message);
  }
  return { ...next, running: false, failure };
}

/** The daemon's git events of the approve call in flight. */
export function applyGitEvent(progress: PublishProgress, event: NestEvent): PublishProgress {
  switch (event.type) {
    case "git.committed":
      return completeStep(progress, "commit");
    case "git.pushed":
      return completeStep(progress, "push");
    case "pr.opened":
      return completeStep(progress, "pr");
    case "git.failed": {
      const { step: name, stderr } = event.payload;
      return failStep(
        progress,
        typeof name === "string" ? name : null,
        typeof stderr === "string" ? stderr : "",
      );
    }
    default:
      return progress;
  }
}
