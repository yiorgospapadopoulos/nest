import { useEffect, useRef, useState, type ReactNode } from "react";
import { commentPlace, reviewCommentsOf } from "../../../api/payloads.ts";
import type { Approval, Session, StuckFlag, TrackedTask } from "../../../api/types.ts";
import { ago } from "../../../format.ts";
import { useCiFailure, useStuck, workRoot } from "../../../screens/approvals/hooks.ts";
import {
  approvalLine,
  approvalPixie,
  checksFailedLine,
  lineText,
  stuckLine,
} from "../../../screens/inbox/needsLine.ts";
import { useStore } from "../../../store/context.ts";
import { goalEntries, inboxGroups, type CiFailure, type Tone } from "../../../store/selectors.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Icon } from "../../../ui/Icon.tsx";
import { ApprovalCard } from "../../chat/ApprovalCard.tsx";
import { Sprite } from "../../pixies/Sprite.tsx";
import { Button } from "../../ui/controls.tsx";
import { useShell } from "../context.ts";
import { approvalFoldKey, useRowOpen } from "./foldRows.ts";

interface FoldProps {
  // Keeps the row open or closed while the app runs.
  rowKey: string;
  tone: Tone;
  openByDefault?: boolean;
  // The chat's (or pixie's) name, which opens it.
  name: ReactNode;
  line: ReactNode;
  label: string;
  children: ReactNode;
}

/**
 * One row of Needs you or Goals, as the Mac's FoldRow (B77): the status dot, the chat's
 * name (which opens it) over one grey line, and a chevron under the card header's. A click
 * anywhere else on the row opens or closes the full item below it, in place.
 */
export function FoldRow({
  rowKey,
  tone,
  openByDefault = false,
  name,
  line,
  label,
  children,
}: FoldProps) {
  const [open, toggleOpen] = useRowOpen(rowKey, openByDefault);
  const row = useRef<HTMLElement>(null);
  // A row the user opens shows whole, rather than cut at the panel's bottom.
  const [opened, setOpened] = useState(0);
  useEffect(() => {
    if (opened > 0) row.current?.scrollIntoView({ block: "nearest" });
  }, [opened]);
  const toggle = () => {
    if (!open) setOpened((n) => n + 1);
    toggleOpen();
  };
  return (
    <article ref={row} className="fr-fold" aria-label={label}>
      <div className="fr-foldrow" onClick={toggle}>
        <span className={`dot s-${tone}`} aria-hidden="true" />
        <span className="fr-foldbody">
          {name}
          <span className="fr-foldline">{line}</span>
        </span>
        <button
          className="fr-foldchev"
          aria-expanded={open}
          aria-label={open ? "Hide details" : "Show details"}
          title={open ? "Hide details" : "Show details"}
          onClick={(event) => {
            event.stopPropagation();
            toggle();
          }}
        >
          <Icon name="chev" />
        </button>
      </div>
      {open && children !== false && <div className="fr-folddetail">{children}</div>}
    </article>
  );
}

/** A chat title that opens the chat, as the Mac's ChatLink. */
function ChatLink({ id, title }: { id: string; title: string }) {
  const shell = useShell();
  return (
    <button
      className="fr-link"
      title="Open this chat"
      onClick={(event) => {
        event.stopPropagation();
        shell.openChat(id);
      }}
    >
      {title}
    </button>
  );
}

/** A pixie's sprite and name that open its page, as the Mac's PixieLink. */
function PixieLink({ id }: { id: string }) {
  const { state } = useStore();
  const shell = useShell();
  const pixie = state.pixies[id];
  return (
    <button
      className="fr-link pixie"
      title="Open this pixie"
      onClick={(event) => {
        event.stopPropagation();
        shell.openPixie(id);
      }}
    >
      {pixie !== undefined && <Sprite mascot={pixie.mascot} color={pixie.color} size={14} />}
      {pixie?.name ?? "Pixie"}
    </button>
  );
}

function Empty({ icon, text, tone }: { icon: "check" | "list"; text: string; tone?: Tone }) {
  return (
    <p className="fr-empty">
      <span className={tone === undefined ? undefined : `t-${tone}`}>
        <Icon name={icon} />
      </span>
      {text}
    </p>
  );
}

/**
 * Pending approvals, failed checks and stuck chats of the project, one short row each that
 * opens to its actions (B77), approvals first, as on the iPhone.
 */
export function NeedsCard({ project }: { project: string }) {
  const { state } = useStore();
  const group = inboxGroups(state).find((g) => g.repo === project);
  const none =
    group === undefined || group.items.length + group.failures.length + group.stuck.length === 0;
  return (
    <>
      {none && <Empty icon="check" text="Nothing needs you." tone="rev" />}
      {group?.items.map((approval) => (
        <ApprovalRow key={approval.id} approval={approval} />
      ))}
      {group?.failures.map((failure) => (
        <FailureRow key={`ci-${failure.session.id}`} failure={failure} />
      ))}
      {group?.stuck.map(({ session, stuck }) => (
        <StuckRow key={`stuck-${session.id}`} session={session} stuck={stuck} />
      ))}
    </>
  );
}

function ApprovalRow({ approval }: { approval: Approval }) {
  const { state } = useStore();
  const session = state.sessions[approval.session_id];
  const green = approval.kind === "review" || approval.kind === "merge";
  const text = lineText(approvalLine(approval, workRoot(session)));
  const pixie = approvalPixie(approval, state.pixieGroups[approval.session_id], state.pixies);
  const pixieChat = approval.repo.startsWith("pixie:") ? approval.repo.slice(6) : null;
  return (
    <FoldRow
      rowKey={approvalFoldKey(approval)}
      tone={green ? "rev" : "wait"}
      label={`${approval.kind}: ${approval.title}`}
      name={
        pixieChat !== null ? (
          <PixieLink id={pixieChat} />
        ) : (
          <ChatLink id={approval.session_id} title={session?.title ?? approval.title} />
        )
      }
      line={
        pixie === null ? (
          text
        ) : (
          <>
            <span className="fr-npix">
              <Sprite mascot={pixie.mascot} color={pixie.color} size={12} phaseKey={pixie.id} />
              {pixie.name}
            </span>
            {` · ${text}`}
          </>
        )
      }
    >
      <ApprovalDetail approval={approval} />
    </FoldRow>
  );
}

/** The approval's card under its row: the chat pane's card in its panel form (wave 2A). */
function ApprovalDetail({ approval }: { approval: Approval }) {
  if (approval.kind === "review_comments") return <CommentsDetail approval={approval} />;
  return <ApprovalCard approval={approval} style="panel" />;
}

function Card({ children }: { children: ReactNode }) {
  return <div className="fr-card">{children}</div>;
}

function Actions({ children }: { children: ReactNode }) {
  return <div className="fr-acts">{children}</div>;
}

/** The pull request's review comments, each sendable alone, then Send all (B101). */
function CommentsDetail({ approval }: { approval: Approval }) {
  const { actions } = useStore();
  const [sending, setSending] = useState<string | null>(null);
  const view = reviewCommentsOf(approval);
  const send = async (key: string, ids?: string[]) => {
    setSending(key);
    await actions.sendReviewComments(approval, ids);
    setSending(null);
  };
  const busy = sending !== null;
  return (
    <Card>
      <p className="fr-why">
        #{view.number}
        {view.changesRequested && " · Changes requested"}
      </p>
      <ul className="fr-comments">
        {view.comments.map((comment) => (
          <li key={comment.id}>
            <span>
              <code title={commentPlace(comment)}>{commentPlace(comment, true)}</code>
              <Button
                kind="link"
                disabled={busy}
                aria-label={`Send ${commentPlace(comment, true)}`}
                onClick={() => void send(comment.id, [comment.id])}
              >
                Send
              </Button>
            </span>
            <p>{comment.body}</p>
          </li>
        ))}
      </ul>
      <Actions>
        {view.comments.length > 0 && (
          <Button kind="primary" disabled={busy} onClick={() => void send("all")}>
            Send all to agent
          </Button>
        )}
        {view.url !== "" && (
          <a className="dk-btn k-link" href={view.url} target="_blank" rel="noreferrer">
            Open on GitHub
          </a>
        )}
      </Actions>
    </Card>
  );
}

function FailureRow({ failure }: { failure: CiFailure }) {
  const { session, pr, names } = failure;
  const { busy, send } = useCiFailure(session);
  return (
    <FoldRow
      rowKey={`Checks failed-${session.id}`}
      tone="fail"
      label={`Checks failed: ${session.title}`}
      name={<ChatLink id={session.id} title={session.title} />}
      line={lineText(checksFailedLine(names))}
    >
      <Card>
        <p className="fr-cq">
          #{pr.number} {pr.title}
        </p>
        <ul className="fr-checks" aria-label="Failing checks">
          {names.map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ul>
        <Actions>
          <Button kind="primary" disabled={busy} onClick={() => void send()}>
            Send to agent
          </Button>
          <a className="dk-btn k-link" href={pr.url} target="_blank" rel="noreferrer">
            Open on GitHub
          </a>
        </Actions>
      </Card>
    </FoldRow>
  );
}

/** A chat that looks stuck: the reason and since when, with Send a nudge and Interrupt. */
function StuckRow({ session, stuck }: { session: Session; stuck: StuckFlag }) {
  const { busy, interrupt, nudge } = useStuck(session.id, stuck.details);
  const line = stuckLine(stuck);
  return (
    <FoldRow
      rowKey={`Stuck-${session.id}`}
      tone="wait"
      label={`Stuck: ${session.title}`}
      name={<ChatLink id={session.id} title={session.title} />}
      line={lineText(line)}
    >
      <Card>
        <div className="fr-stuckhead">
          <b>{line.detail ?? "Stuck"}</b>
          <small>for {ago(stuck.since, new Date())}</small>
        </div>
        <p className="fr-why">{stuck.details}</p>
        <Actions>
          <Button
            kind="primary"
            disabled={busy}
            onClick={() => void nudge()}
            title="Stops the turn and sends a nudge"
          >
            <Icon name="send" />
            Send a nudge
          </Button>
          <Button
            kind="plain"
            disabled={busy}
            onClick={() => void interrupt()}
            title="Stops the turn"
          >
            Interrupt
          </Button>
        </Actions>
      </Card>
    </FoldRow>
  );
}

/**
 * What each chat of the project is planning and doing (D092): every chat working or with
 * tasks in its list, as a row with its progress that opens to its checklist (B77), open
 * unless the user closed it.
 */
export function GoalsCard({ project }: { project: string }) {
  const { state, actions } = useStore();
  useEffect(() => {
    void actions.loadGoals(project);
  }, [actions, project]);
  const entries = goalEntries(state, project);
  if (entries.length === 0) return <Empty icon="list" text="No chats working" />;
  return (
    <>
      {entries.map(({ session, status, tasks }) => {
        const done = tasks.filter((t) => t.status === "completed").length;
        const progress =
          tasks.length === 0 ? "No plan yet" : `${String(done)} of ${String(tasks.length)}`;
        return (
          <FoldRow
            key={session.id}
            rowKey={`goal-${session.id}`}
            tone={status.tone}
            openByDefault
            label={`${session.title}: ${progress}, ${status.label}`}
            name={<ChatLink id={session.id} title={session.title} />}
            line={
              <span className="fr-progress">
                <span>{progress}</span>
                {tasks.length > 0 && (
                  <span className="fr-track" aria-hidden="true">
                    <i style={{ width: `${String((100 * done) / tasks.length)}%` }} />
                  </span>
                )}
              </span>
            }
          >
            {tasks.length > 0 && <Checklist tasks={tasks} />}
          </FoldRow>
        );
      })}
    </>
  );
}

function Checklist({ tasks }: { tasks: TrackedTask[] }) {
  return (
    <ol className="fr-steps">
      {tasks.map((task, index) => (
        <li key={task.id} className={task.status === "completed" ? "fr-stepdone" : undefined}>
          <span className="fr-stepmark" aria-hidden="true">
            {task.status === "completed" ? (
              <Icon name="check" />
            ) : task.status === "in_progress" ? (
              <Fireflies size={9} />
            ) : (
              <i />
            )}
          </span>
          <span className="fr-stepn">{index + 1}</span>
          <span className="fr-stept">
            {task.subject}
            {task.status === "in_progress" && task.active_form !== null && (
              <small>{task.active_form}</small>
            )}
          </span>
        </li>
      ))}
    </ol>
  );
}
