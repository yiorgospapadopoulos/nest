import { useEffect, useState } from "react";
import type { CheckState, PrState, PrStatus, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import type { Tone } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { Sheet } from "../../ui/Sheet.tsx";
import { ArtifactsSheet } from "../artifacts/ArtifactsSheet.tsx";
import { chatScopes } from "../artifacts/view.ts";
import {
  guideView,
  offersGuide,
  MERGE_WHEN_READY,
  mergesWhenReady,
  mergeWhenReadyLine,
  onTopBranch,
  restackAction,
  stackParent,
} from "./prWork.ts";
import { prView } from "./prView.ts";

interface ChatLinks {
  onOpenChat: (sessionId: string) => void;
  // A new chat in the chat's project on a new worktree from `branch`.
  onNewChatOnTop: (branch: string) => void;
}

interface Shown {
  id: string;
  version: number;
}

/** The chat's pull request with a dot for its checks; opens its details. */
export function PrChip({ session, onOpenChat, onNewChatOnTop }: { session: Session } & ChatLinks) {
  const [open, setOpen] = useState(false);
  // The review guide, opened from the details in the artifact reader.
  const [guide, setGuide] = useState<Shown | null>(null);
  if (session.pr_url === null) return null;
  const { label, tone, text } = prView(session.pr, session.pr_url);
  return (
    <>
      <button
        className="chip prchip"
        aria-haspopup="dialog"
        aria-label={`Pull request ${label}, ${text}`}
        onClick={() => {
          setOpen(true);
        }}
      >
        <Dot tone={tone} />
        <span>{label}</span>
      </button>
      {open && (
        <PrSheet
          session={session}
          label={label}
          onClose={() => {
            setOpen(false);
          }}
          onOpenChat={(id) => {
            setOpen(false);
            onOpenChat(id);
          }}
          onNewChatOnTop={(branch) => {
            setOpen(false);
            onNewChatOnTop(branch);
          }}
          onOpenGuide={(shown) => {
            setOpen(false);
            setGuide(shown);
          }}
        />
      )}
      {guide !== null && (
        <ArtifactsSheet
          scopes={chatScopes(session)}
          open={guide}
          onClose={() => {
            setGuide(null);
          }}
        />
      )}
    </>
  );
}

/** "#47" beside the pull request's chip: the issue the chat was started from (B101). */
export function IssueChip({ session }: { session: Session }) {
  const { issue } = session;
  if (issue === null) return null;
  return (
    <a
      className="chip prchip"
      href={issue.url}
      target="_blank"
      rel="noreferrer"
      aria-label={`Issue #${String(issue.number)}, ${issue.title}`}
    >
      <span>#{issue.number}</span>
    </a>
  );
}

const STATES: Record<PrState, string> = { open: "Open", merged: "Merged", closed: "Closed" };

const CHECKS: Record<CheckState, { tone: Tone; label: string }> = {
  pending: { tone: "run", label: "Running" },
  success: { tone: "rev", label: "Passed" },
  skipped: { tone: "idle", label: "Skipped" },
  failure: { tone: "fail", label: "Failed" },
};

/** "2 failed, 1 running, 3 passed", as NestKit's PRBadge.checksSummary. */
function checksSummary(checks: PrStatus["checks"]): string {
  const parts = [
    checks.failed > 0 ? `${String(checks.failed)} failed` : null,
    checks.pending > 0 ? `${String(checks.pending)} running` : null,
    checks.passed > 0 ? `${String(checks.passed)} passed` : null,
  ].filter((part) => part !== null);
  return parts.length === 0 ? "No checks" : parts.join(", ");
}

const AUTO_SEND = "Send review comments on their own";

/**
 * The pull request with, for a chat from an issue, the issue it closes on merge, and for a
 * stacked chat the chat under it; then its checks, whether review comments go to the agent
 * on their own, merge when checks pass, moving the branch, the review guide, a new chat on
 * top, Refresh and Open on GitHub. As the Mac's PR popover (B101, B149).
 */
function PrSheet({
  session,
  label,
  onClose,
  onOpenChat,
  onNewChatOnTop,
  onOpenGuide,
}: {
  session: Session;
  label: string;
  onClose: () => void;
  onOpenGuide: (guide: Shown) => void;
} & ChatLinks) {
  const { state, actions } = useStore();
  const [refreshing, setRefreshing] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [merging, setMerging] = useState(false);
  const { pr, issue } = session;
  const url = pr?.url ?? session.pr_url ?? "";
  const autoSend = session.review?.auto_send ?? false;
  const mergeOn = mergesWhenReady(session);
  const mergeLine = mergeWhenReadyLine(session);
  const parent = stackParent(state, session);
  const onTop = onTopBranch(session);
  const guide = pr !== null && offersGuide(state, session, pr);
  const status = pr === null ? null : `${STATES[pr.state]} · ${checksSummary(pr.checks)}`;
  return (
    <Sheet title={`Pull request ${label}`} onClose={onClose}>
      <div className="prs">
        <a className="prs-t" href={url} target="_blank" rel="noreferrer">
          <span className="prs-n">{label}</span> {pr?.title ?? session.title}
        </a>
        {issue !== null && (
          <>
            <div className="prs-c">
              <Icon name="send" />
              Closes #{issue.number} on merge
            </div>
            <a className="prs-t" href={issue.url} target="_blank" rel="noreferrer">
              <span className="prs-n">#{issue.number}</span> {issue.title}
            </a>
          </>
        )}
        {parent !== null && (
          <button
            className="prs-c prs-up"
            disabled={parent.id === null}
            onClick={() => {
              if (parent.id !== null) onOpenChat(parent.id);
            }}
          >
            <Icon name="branch" />
            {parent.text}
          </button>
        )}
        {status !== null && (
          <div className="prs-s">{issue === null ? status : `${label} · ${status}`}</div>
        )}
        {pr !== null && pr.checks.items.length > 0 && (
          <ul className="prs-k" aria-label="Checks">
            {pr.checks.items.map((check) => (
              <li key={check.name}>
                <Dot tone={CHECKS[check.state].tone} />
                <span className="prs-kn">{check.name}</span>
                <span className="prs-kv">{CHECKS[check.state].label}</span>
              </li>
            ))}
          </ul>
        )}
        {pr?.state === "open" && (
          <div className="prs-a">
            <span className="prs-al">
              <span id={`autosend-${session.id}`}>{AUTO_SEND}</span>
              <small>
                {autoSend
                  ? "New comments go to the agent as they arrive"
                  : "Off: they wait in Needs you"}
              </small>
            </span>
            <button
              className="sw"
              role="switch"
              aria-checked={autoSend}
              aria-labelledby={`autosend-${session.id}`}
              disabled={switching}
              onClick={() => {
                setSwitching(true);
                void actions.setReviewAutoSend(session.id, !autoSend).finally(() => {
                  setSwitching(false);
                });
              }}
            />
          </div>
        )}
        {pr?.state === "open" && (
          <div className="prs-a">
            <span className="prs-al">
              <span id={`mergeready-${session.id}`}>{MERGE_WHEN_READY}</span>
              {mergeLine !== null && <small>{mergeLine}</small>}
            </span>
            <button
              className="sw"
              role="switch"
              aria-checked={mergeOn}
              aria-labelledby={`mergeready-${session.id}`}
              disabled={merging}
              onClick={() => {
                setMerging(true);
                void actions.setMergeWhenReady(session.id, !mergeOn).finally(() => {
                  setMerging(false);
                });
              }}
            />
          </div>
        )}
        <RestackRow session={session} />
        {guide && <GuideRow session={session} pr={pr} onOpen={onOpenGuide} />}
        {onTop !== null && (
          <div className="acts">
            <button
              className="b"
              onClick={() => {
                onNewChatOnTop(onTop);
              }}
            >
              <Icon name="plus" />
              New chat on top
            </button>
          </div>
        )}
        <div className="acts">
          <button
            className="b"
            disabled={refreshing}
            onClick={() => {
              setRefreshing(true);
              void actions.refreshPr(session.id).finally(() => {
                setRefreshing(false);
              });
            }}
          >
            Refresh
          </button>
          <a className="b qb2" href={url} target="_blank" rel="noreferrer">
            Open on GitHub
          </a>
        </div>
      </div>
    </Sheet>
  );
}

/** Where a stacked chat's branch has to move, with the one button that moves it (B149). */
function RestackRow({ session }: { session: Session }) {
  const { actions } = useStore();
  const [busy, setBusy] = useState(false);
  const restack = session.stack?.restack ?? null;
  if (restack === null) return null;
  const action = restackAction(restack.rebased !== null, session.pr?.state === "open");
  return (
    <div className="prs-a">
      <span className="prs-al">
        <span>Moves onto {restack.base}</span>
        {restack.error !== null && <small>{restack.error}</small>}
      </span>
      <button
        className="b b-pri"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          void actions.restack(session.id, action.done).finally(() => {
            setBusy(false);
          });
        }}
      >
        {action.label}
      </button>
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
  onOpen,
}: {
  session: Session;
  pr: PrStatus;
  onOpen: (guide: Shown) => void;
}) {
  const { state, actions } = useStore();
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
    <button
      className="b"
      disabled={busy}
      onClick={() => {
        run(() => actions.writePrGuide(session.id));
      }}
    >
      {label}
    </button>
  );
  switch (view.kind) {
    case "none":
      return <div className="acts">{write("Write review guide")}</div>;
    case "writing":
      return (
        <div className="prs-a">
          <span className="prs-al">Writing the review guide</span>
          <Fireflies size={10} />
        </div>
      );
    case "failed":
      return (
        <div className="prs-a">
          <span className="prs-al">
            <span>Review guide</span>
            <small>{view.error}</small>
          </span>
          {write("Try again")}
        </div>
      );
    case "ready":
      return (
        <div className="prs-a">
          <span className="prs-al">
            <span>Review guide</span>
            {view.stale && <small>Written for an earlier commit</small>}
          </span>
          <button
            className="b"
            disabled={artifact === undefined}
            onClick={() => {
              if (artifact !== undefined)
                onOpen({ id: artifact.id, version: artifact.latest_version });
            }}
          >
            Open
          </button>
          {view.stale ? (
            write("Write again")
          ) : view.commentUrl === null ? (
            <button
              className="b"
              disabled={busy}
              onClick={() => {
                run(() => actions.postPrGuide(session.id));
              }}
            >
              Post on GitHub
            </button>
          ) : (
            <a className="b qb2" href={view.commentUrl} target="_blank" rel="noreferrer">
              Posted on GitHub
            </a>
          )}
        </div>
      );
  }
}
