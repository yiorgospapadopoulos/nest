import { use, useEffect, useRef, useState, type ReactNode } from "react";
import type { CheckState, PrState, PrStatus, Session } from "../../../api/types.ts";
import {
  guideView,
  offersGuide,
  MERGE_WHEN_READY,
  mergesWhenReady,
  mergeWhenReadyLine,
  onTopBranch,
  restackAction,
  stackParent,
} from "../../../screens/chat/prWork.ts";
import { useStore } from "../../../store/context.ts";
import type { Tone } from "../../../store/selectors.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Icon } from "../../../ui/Icon.tsx";
import { openArtifact } from "../../artifacts/viewState.ts";
import { Glyph } from "../../chat/glyphs.tsx";
import { Button, Toggle } from "../../ui/controls.tsx";
import { Popover } from "../../ui/Popover.tsx";
import { ShellContext } from "../context.ts";
import { checksSummary, prDot } from "./pr.ts";

const STATES: Record<PrState, string> = { open: "Open", merged: "Merged", closed: "Closed" };

const CHECKS: Record<CheckState, { tone: Tone; label: string }> = {
  pending: { tone: "wait", label: "Running" },
  success: { tone: "rev", label: "Passed" },
  skipped: { tone: "idle", label: "Skipped" },
  failure: { tone: "fail", label: "Failed" },
};

const AUTO_SEND = "Send review comments on their own";

/** GitHub's pull request mark, as the Mac's PullRequestGlyph. */
export function PullRequestGlyph({ size }: { size: number }) {
  return (
    <svg className="fr-prglyph" width={size} height={size} viewBox="0 0 100 100" aria-hidden="true">
      <circle cx="25" cy="20" r="12" />
      <circle cx="25" cy="80" r="12" />
      <circle cx="75" cy="80" r="12" />
      <path d="M25 32V68M75 68V38Q75 20 57 20H45M56 9L45 20L56 31" />
    </svg>
  );
}

/** GitHub's open issue mark: a ring with a dot. */
function IssueGlyph() {
  return (
    <svg className="fr-prglyph" width={11} height={11} viewBox="0 0 12 12" aria-hidden="true">
      <circle cx="6" cy="6" r="4.8" />
      <circle cx="6" cy="6" r="1.2" className="fill" />
    </svg>
  );
}

/**
 * "#118" with its checks' dot, as the Mac's PRChip; a click opens the pull request's details
 * in a popover below it.
 */
export function PrChip({ session, pr }: { session: Session; pr: PrStatus }) {
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const dot = prDot(pr);
  return (
    <>
      <button
        ref={anchor}
        className="fr-prchip"
        title={`Pull request #${String(pr.number)}: ${checksSummary(pr.checks)}`}
        aria-label={`Pull request ${String(pr.number)}, ${STATES[pr.state]}, ${checksSummary(pr.checks)}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
      >
        <PullRequestGlyph size={11} />
        <span>#{pr.number}</span>
        <span className={dot.hollow ? `dot s-${dot.tone} hollow` : `dot s-${dot.tone}`} />
      </button>
      {open && (
        <Popover
          anchor={anchor}
          label={`Pull request #${String(pr.number)}`}
          align="start"
          className="fr-prpop"
          onClose={() => {
            setOpen(false);
          }}
        >
          <PrDetails
            session={session}
            pr={pr}
            onClose={() => {
              setOpen(false);
            }}
          />
        </Popover>
      )}
    </>
  );
}

function LinkLine({
  mark,
  number,
  title,
  url,
}: {
  mark: ReactNode;
  number: number;
  title: string;
  url: string;
}) {
  return (
    <a className="fr-prline" href={url} target="_blank" rel="noreferrer">
      <span className="fr-prmark">{mark}</span>
      <span className="fr-prnum">#{number}</span>
      <span className="fr-prtitle">{title}</span>
    </a>
  );
}

/**
 * The pull request with, for a chat from an issue, the issue it closes on merge, and for a
 * stacked chat the chat under it; then its checks, whether review comments go to the agent
 * on their own, merge when checks pass, moving the branch, the review guide, a new chat on
 * top, Refresh and Open on GitHub.
 */
function PrDetails({
  session,
  pr,
  onClose,
}: {
  session: Session;
  pr: PrStatus;
  onClose: () => void;
}) {
  const { state, actions } = useStore();
  const shell = use(ShellContext);
  const [refreshing, setRefreshing] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [merging, setMerging] = useState(false);
  const { issue } = session;
  const autoSend = session.review?.auto_send ?? false;
  const mergeOn = mergesWhenReady(session);
  const mergeLine = mergeWhenReadyLine(session);
  const parent = stackParent(state, session);
  const onTop = onTopBranch(session);
  const status = `${STATES[pr.state]} · ${checksSummary(pr.checks)}`;
  return (
    <div className="fr-prd">
      <div className="fr-prhead">
        <LinkLine
          mark={<PullRequestGlyph size={12} />}
          number={pr.number}
          title={pr.title}
          url={pr.url}
        />
        {issue !== null && (
          <>
            <span className="fr-prcloses">
              <span>↑</span>
              Closes #{issue.number} on merge
            </span>
            <LinkLine
              mark={<IssueGlyph />}
              number={issue.number}
              title={issue.title}
              url={issue.url}
            />
          </>
        )}
        {parent !== null && (
          <button
            className="fr-prcloses fr-prstack"
            disabled={parent.id === null || shell === null}
            onClick={() => {
              if (parent.id === null) return;
              shell?.openChat(parent.id);
              onClose();
            }}
          >
            <span>
              <Glyph name="branch" size={10} />
            </span>
            {parent.text}
          </button>
        )}
        <span className="fr-prstatus">
          {issue === null ? status : `#${String(pr.number)} · ${status}`}
        </span>
      </div>
      {pr.checks.items.length > 0 && (
        <ul className="fr-prchecks" aria-label="Checks">
          {pr.checks.items.map((check) => (
            <li key={check.name}>
              <span className={`dot s-${CHECKS[check.state].tone}`} />
              <span className="fr-prcn">{check.name}</span>
              <span className="fr-prcv">{CHECKS[check.state].label}</span>
            </li>
          ))}
        </ul>
      )}
      {pr.state === "open" && (
        <div className="fr-prauto">
          <span>
            {AUTO_SEND}
            <small>
              {autoSend
                ? "New comments go to the agent as they arrive"
                : "Off: they wait in Needs you"}
            </small>
          </span>
          <Toggle
            checked={autoSend}
            label={AUTO_SEND}
            disabled={switching}
            onChange={(on) => {
              setSwitching(true);
              void actions.setReviewAutoSend(session.id, on).finally(() => {
                setSwitching(false);
              });
            }}
          />
        </div>
      )}
      {pr.state === "open" && (
        <div className="fr-prauto">
          <span>
            {MERGE_WHEN_READY}
            {mergeLine !== null && <small>{mergeLine}</small>}
          </span>
          <Toggle
            checked={mergeOn}
            label={MERGE_WHEN_READY}
            disabled={merging}
            onChange={(on) => {
              setMerging(true);
              void actions.setMergeWhenReady(session.id, on).finally(() => {
                setMerging(false);
              });
            }}
          />
        </div>
      )}
      <RestackRow session={session} pr={pr} />
      {offersGuide(state, session, pr) && <GuideRow session={session} pr={pr} onClose={onClose} />}
      {onTop !== null && shell !== null && (
        <div className="fr-prbtns">
          <Button
            title={`A new chat in a worktree that starts from ${onTop}`}
            onClick={() => {
              shell.newWorktreeFrom(onTop);
              onClose();
            }}
          >
            <Glyph name="plus" size={10} />
            New chat on top
          </Button>
        </div>
      )}
      <div className="fr-prbtns">
        <Button
          disabled={refreshing}
          title="Read the pull request from GitHub now"
          onClick={() => {
            setRefreshing(true);
            void actions.refreshPr(session.id).finally(() => {
              setRefreshing(false);
            });
          }}
        >
          {refreshing ? <Fireflies size={9} /> : <Icon name="restart" />}
          Refresh
        </Button>
        <span className="grow" />
        <a className="dk-btn k-link" href={pr.url} target="_blank" rel="noreferrer">
          Open on GitHub
        </a>
      </div>
    </div>
  );
}

/** Where a stacked chat's branch has to move, with the one button that moves it (B149). */
function RestackRow({ session, pr }: { session: Session; pr: PrStatus }) {
  const { actions } = useStore();
  const [busy, setBusy] = useState(false);
  const restack = session.stack?.restack ?? null;
  if (restack === null) return null;
  const action = restackAction(restack.rebased !== null, pr.state === "open");
  return (
    <div className="fr-prauto">
      <span>
        Moves onto {restack.base}
        {restack.error !== null && <small>{restack.error}</small>}
      </span>
      <Button
        kind="primary"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          void actions.restack(session.id, action.done).finally(() => {
            setBusy(false);
          });
        }}
      >
        {busy && <Fireflies size={9} />}
        {action.label}
      </Button>
    </div>
  );
}

/**
 * The pull request's review guide (B149): Write review guide, then Open and Post on GitHub
 * once it is written, or a link to the comment once posted. A guide of an older head offers
 * Write again; a failed one shows why and Try again.
 */
function GuideRow({
  session,
  pr,
  onClose,
}: {
  session: Session;
  pr: PrStatus;
  onClose: () => void;
}) {
  const { state, actions } = useStore();
  const shell = use(ShellContext);
  const [busy, setBusy] = useState(false);
  const view = guideView(session, pr);
  const artifactId = view.kind === "ready" ? view.artifactId : null;
  const artifact = artifactId === null ? undefined : state.artifacts[artifactId];
  const known = artifact !== undefined;
  useEffect(() => {
    if (artifactId !== null && !known) void actions.loadArtifact(artifactId);
  }, [actions, artifactId, known]);
  const run = (call: () => Promise<boolean>) => {
    setBusy(true);
    void call().finally(() => {
      setBusy(false);
    });
  };
  const write = (label: string) => (
    <Button
      disabled={busy}
      onClick={() => {
        run(() => actions.writePrGuide(session.id));
      }}
    >
      {label}
    </Button>
  );
  switch (view.kind) {
    case "none":
      return <div className="fr-prbtns">{write("Write review guide")}</div>;
    case "writing":
      return (
        <div className="fr-prauto">
          <span>Writing the review guide</span>
          <Fireflies size={9} />
        </div>
      );
    case "failed":
      return (
        <div className="fr-prauto">
          <span>
            Review guide
            <small>{view.error}</small>
          </span>
          {write("Try again")}
        </div>
      );
    case "ready":
      return (
        <div className="fr-prauto">
          <span>
            Review guide
            {view.stale && <small>Written for an earlier commit</small>}
          </span>
          <Button
            disabled={artifact === undefined || shell === null}
            onClick={() => {
              if (artifact === undefined || shell === null) return;
              openArtifact(shell, artifact.id, artifact.latest_version, session.id);
              onClose();
            }}
          >
            Open
          </Button>
          {view.stale ? (
            write("Write again")
          ) : view.commentUrl === null ? (
            <Button
              disabled={busy}
              onClick={() => {
                run(() => actions.postPrGuide(session.id));
              }}
            >
              Post on GitHub
            </Button>
          ) : (
            <a className="dk-btn k-link" href={view.commentUrl} target="_blank" rel="noreferrer">
              Posted on GitHub
            </a>
          )}
        </div>
      );
  }
}
