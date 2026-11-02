import { useState } from "react";
import type { CheckState, PrState, PrStatus, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import type { Tone } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { Sheet } from "../../ui/Sheet.tsx";
import { prView } from "./prView.ts";

/** The chat's pull request with a dot for its checks; opens its details. */
export function PrChip({ session }: { session: Session }) {
  const [open, setOpen] = useState(false);
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
 * The pull request with, for a chat from an issue, the issue it closes on merge; then its
 * checks, whether review comments go to the agent on their own, Refresh and Open on GitHub.
 * As the Mac's PR popover (B101).
 */
function PrSheet({
  session,
  label,
  onClose,
}: {
  session: Session;
  label: string;
  onClose: () => void;
}) {
  const { actions } = useStore();
  const [refreshing, setRefreshing] = useState(false);
  const [switching, setSwitching] = useState(false);
  const { pr, issue } = session;
  const url = pr?.url ?? session.pr_url ?? "";
  const autoSend = session.review?.auto_send ?? false;
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
