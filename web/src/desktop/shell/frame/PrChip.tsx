import { useRef, useState, type ReactNode } from "react";
import type { CheckState, PrState, PrStatus, Session } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import type { Tone } from "../../../store/selectors.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Icon } from "../../../ui/Icon.tsx";
import { Button, Toggle } from "../../ui/controls.tsx";
import { Popover } from "../../ui/Popover.tsx";
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
          <PrDetails session={session} pr={pr} />
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
 * The pull request with, for a chat from an issue, the issue it closes on merge; then its
 * checks, whether review comments go to the agent on their own, Refresh and Open on GitHub.
 */
function PrDetails({ session, pr }: { session: Session; pr: PrStatus }) {
  const { actions } = useStore();
  const [refreshing, setRefreshing] = useState(false);
  const [switching, setSwitching] = useState(false);
  const { issue } = session;
  const autoSend = session.review?.auto_send ?? false;
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
