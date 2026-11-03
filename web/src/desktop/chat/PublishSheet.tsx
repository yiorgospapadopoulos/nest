// Approving a review, as the Mac's PublishSheet: the commit message and, for a worktree
// chat without a pull request, the pull request choice, then each git step's progress; a
// failed step shows its error output and can be tried again. With an open pull request,
// Approve and push sits beside Approve and commit, which only commits (B101).
import { useEffect, useRef, useState } from "react";
import type { Approval, Session } from "../../api/types.ts";
import { COMMIT_TITLE, type Review } from "../../screens/approvals/hooks.ts";
import { useStore } from "../../store/context.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { useApi } from "../context.ts";
import { Button, Toggle } from "../ui/controls.tsx";
import { DiffCounts } from "./bits.tsx";
import { Glyph } from "./glyphs.tsx";
import {
  applyGitEvent,
  approveBody,
  canOpenPR,
  canSubmit,
  doneText,
  failProgress,
  finishProgress,
  formNote,
  formReplyNote,
  formTitle,
  publishFailure,
  publishForm,
  pushes,
  pushTitle,
  remoteSummary,
  remoteTarget,
  startProgress,
  steps,
  STEP_TITLES,
  type PublishForm,
  type PublishProgress,
  type PublishStep,
  type PushRemote,
} from "./publish.ts";
import { PublishTarget } from "./ReviewSheets.tsx";
import { Sheet } from "./Sheet.tsx";

interface Props {
  approval: Approval;
  session: Session | undefined;
  review: Review;
  // Opened from Approve and commit beside Approve and push to #N.
  commitOnly: boolean;
  onClose: () => void;
}

export function PublishSheet({ approval, session, review, commitOnly, onClose }: Props) {
  const api = useApi();
  const { actions } = useStore();
  const [form, setForm] = useState(() => publishForm(approval, session, commitOnly));
  const [progress, setProgress] = useState<PublishProgress | null>(null);
  const open = useRef(true);
  const { loadDiff } = review;
  // Approve sends the HEAD and fingerprint of the diff it shows, so it is read again on
  // every opening and Approve waits for it.
  useEffect(() => {
    loadDiff();
    open.current = true;
    return () => {
      open.current = false;
    };
  }, [loadDiff]);
  const running = progress?.running ?? false;
  const update = (change: Partial<PublishForm>) => {
    setForm((current) => ({ ...current, ...change }));
  };

  const publish = async (sent: PublishForm) => {
    const seen = review.diff;
    if (seen === null || !review.ready) return;
    setForm(sent);
    setProgress(startProgress(steps(sent)));
    const stop = actions.onEvent((event) => {
      if (event.session_id === approval.session_id) {
        setProgress((current) => (current === null ? null : applyGitEvent(current, event)));
      }
    });
    try {
      await api.approve(approval.session_id, approveBody(sent, seen));
      stop();
      setProgress((current) => (current === null ? null : finishProgress(current)));
      actions.toast(doneText(sent, approval.title));
      if (open.current) onClose();
    } catch (error) {
      stop();
      const failure = publishFailure(error);
      setProgress((current) => (current === null ? null : failProgress(current, failure)));
      // A refusal: show the branch as it is now.
      if (failure.refused) loadDiff();
    }
  };

  const title = formTitle(form);
  const blocked = running || !review.ready || !canSubmit(form);
  const failed = progress?.failure != null;
  const note = formNote(form);
  const reply = formReplyNote(form);
  return (
    <Sheet title={title} onClose={onClose} width={540}>
      <div className="dc-pub">
        <div className="dc-pubh">
          <span className="dc-pubt">{approval.title}</span>
          <DiffCounts
            added={review.view.additions}
            removed={review.view.deletions}
            files={review.view.files}
          />
        </div>
        {review.diff !== null && <PublishTarget diff={review.diff} pushes={pushes(form)} />}
        {review.diffFailed ? (
          <p className="dc-pubnote bad">Could not read the changes.</p>
        ) : (
          !review.ready && (
            <p className="dc-pubnote">
              <Fireflies size={9} />
              Reading the changes…
            </p>
          )
        )}
        <label className="dc-flabel" htmlFor="dc-commit">
          Commit message
        </label>
        <textarea
          id="dc-commit"
          className="dc-sfield"
          rows={3}
          value={form.commitMessage}
          disabled={running}
          data-autofocus
          onChange={(event) => {
            update({ commitMessage: event.target.value });
          }}
        />
        {canOpenPR(form) && (
          <div className="dc-pubrow">
            <span>Push and open a pull request</span>
            <Toggle
              label="Push and open a pull request"
              checked={form.openPR}
              disabled={running}
              onChange={(openPR) => {
                update({ openPR });
              }}
            />
          </div>
        )}
        {note !== null && <p className="dc-pubnote">{note}</p>}
        {reply !== null && <p className="dc-pubnote">{reply}</p>}
        {steps(form).includes("pr") && (
          <>
            <label className="dc-flabel" htmlFor="dc-prtitle">
              Pull request title (optional)
            </label>
            <input
              id="dc-prtitle"
              className="dc-sfield"
              placeholder={form.commitMessage}
              autoComplete="off"
              value={form.prTitle}
              disabled={running}
              onChange={(event) => {
                update({ prTitle: event.target.value });
              }}
            />
            <label className="dc-flabel" htmlFor="dc-prbody">
              Pull request description (optional)
            </label>
            <textarea
              id="dc-prbody"
              className="dc-sfield"
              rows={3}
              placeholder="Optional"
              value={form.prBody}
              disabled={running}
              onChange={(event) => {
                update({ prBody: event.target.value });
              }}
            />
          </>
        )}
        {progress !== null && (
          <StepList
            progress={progress}
            busy={running}
            pushThere={(url) => {
              void publish({ ...form, confirmRemoteUrl: url });
            }}
          />
        )}
        <div className="dc-sheet-acts">
          <Button onClick={onClose}>Cancel</Button>
          {form.pullRequest !== null ? (
            <>
              <Button
                kind="plain"
                disabled={blocked}
                title="Commit without pushing; the pull request stays as it is"
                onClick={() => {
                  void publish({ ...form, pushToPR: false });
                }}
              >
                {!form.pushToPR && failed ? "Try again" : COMMIT_TITLE}
              </Button>
              <Button
                kind="primary"
                disabled={blocked}
                onClick={() => {
                  void publish({ ...form, pushToPR: true });
                }}
              >
                {running && form.pushToPR ? <Fireflies size={9} /> : <Glyph name="pr" size={10} />}
                {running && form.pushToPR
                  ? "Publishing…"
                  : form.pushToPR && failed
                    ? "Try again"
                    : pushTitle(form.pullRequest)}
              </Button>
            </>
          ) : (
            <Button
              kind="primary"
              disabled={blocked}
              onClick={() => {
                void publish(form);
              }}
            >
              {running ? (
                <Fireflies size={9} />
              ) : (
                <Glyph name={pushes(form) ? "pr" : "check"} size={10} />
              )}
              {running ? "Publishing…" : failed ? "Try again" : title}
            </Button>
          )}
        </div>
      </div>
    </Sheet>
  );
}

const STATE_LABELS: Record<PublishStep["state"], string> = {
  pending: "Waiting",
  running: "Running",
  done: "Done",
  failed: "Failed",
};

function StepMark({ state }: { state: PublishStep["state"] }) {
  switch (state) {
    case "pending":
      return <span className="dc-stepdot" />;
    case "running":
      return <Fireflies size={9} />;
    case "done":
      return <Glyph name="check" size={10} className="dc-ok" />;
    case "failed":
      return <Glyph name="close" size={10} className="dc-bad" />;
  }
}

/** Commit, push and pull request with their state; a failed step shows git's output. */
function StepList({
  progress,
  busy,
  pushThere,
}: {
  progress: PublishProgress;
  busy: boolean;
  pushThere: (url: string) => void;
}) {
  const { failure } = progress;
  const stepFailed = progress.steps.some((s) => s.state === "failed");
  return (
    <div className="dc-steps" aria-label="Approve steps">
      {progress.steps.map((step) => (
        <div key={step.kind} className="dc-step">
          <div className="dc-steph">
            <span className="dc-stepm">
              <StepMark state={step.state} />
            </span>
            <span className="grow">{STEP_TITLES[step.kind]}</span>
            <span className="dc-stepl">{STATE_LABELS[step.state]}</span>
          </div>
          {step.state === "failed" && <pre className="dc-stepo">{step.output}</pre>}
        </div>
      ))}
      {failure !== null &&
        (stepFailed ? (
          <>
            <p className="dc-stepn">{failure.message}</p>
            <p className="dc-stepn">
              The review stays open. Fix the cause and try again; finished steps are skipped.
            </p>
          </>
        ) : (
          <>
            {/* Refused before any step ran: the daemon's reason, and what to do. */}
            <p className="dc-stepn bad">{failure.message}</p>
            {failure.hint !== null && <p className="dc-stepn">{failure.hint}</p>}
            {failure.remote !== null && (
              <RemoteConfirmation remote={failure.remote} busy={busy} push={pushThere} />
            )}
          </>
        ))}
    </div>
  );
}

/** Where origin pushes now, after approving was refused for it, and Push there (I-008). */
function RemoteConfirmation({
  remote,
  busy,
  push,
}: {
  remote: PushRemote;
  busy: boolean;
  push: (url: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollIntoView({ block: "nearest" });
  }, []);
  const target = remoteTarget(remote);
  return (
    <div ref={ref} className="dc-remote" role="alert">
      <span>{remoteSummary(remote)}</span>
      {remote.urls.map((url) => (
        <code key={url}>{url}</code>
      ))}
      {remote.confirmed !== null && <span>Confirmed before: {remote.confirmed}</span>}
      {target !== null && (
        <Button
          kind="primary"
          disabled={busy}
          title="Approve again and remember this address for the project"
          onClick={() => {
            push(target);
          }}
        >
          <Glyph name="send" size={10} />
          Push there
        </Button>
      )}
    </div>
  );
}
