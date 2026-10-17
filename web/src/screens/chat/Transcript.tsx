import {
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type ReactNode,
} from "react";
import type {
  BackgroundSummary,
  GroupEntry,
  Pixie,
  PixieTeam,
  Restore,
  RewindPreview,
  Session,
  ShellResult,
  TeamMember,
} from "../../api/types.ts";
import { asDraftFiles } from "../../store/actions.ts";
import { useStore } from "../../store/context.ts";
import { draftKey, type BashRun, type HistoryStatus } from "../../store/state.ts";
import { elapsed, summarizeTools, thoughtLabel, toolKind } from "../../transcript/activity.ts";
import {
  buildTranscript,
  turnStart,
  type HookItem,
  type PixieCallItem,
  type SubStep,
  type ThinkingItem,
  type ToolItem,
  type TranscriptItem,
} from "../../transcript/build.ts";
import { mentionColors, mentionParts } from "../../transcript/mentions.ts";
import type { DiffLine, EditDiff } from "../../transcript/edits.ts";
import { outputPreview } from "../../transcript/output.ts";
import { Icon } from "../../ui/Icon.tsx";
import { toolIcon } from "../../ui/toolIcon.ts";
import { usePageVisible } from "../../ui/visible.ts";
import { workRoot } from "../approvals/hooks.ts";
import { Sprite } from "../pixies/Sprite.tsx";
import { TeamFace } from "../pixies/TeamFace.tsx";
import type { WorkOf } from "../projects/ChatTree.tsx";
import { InlineApproval } from "./InlineApproval.tsx";
import { PixieCard } from "./PixieCard.tsx";
import { ResultImages } from "./ResultImages.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";
import { changesFiles } from "./rewind.ts";
import { EditSheet, RewindSheet } from "./RewindSheet.tsx";
import { usePrefill } from "./usePrefill.tsx";
import { StopTask } from "./StopTask.tsx";
import { CallContext, useStopTask, type CallControls } from "./useStopTask.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";

// Within this many pixels of the bottom, new output is followed. Anywhere else the
// reading position never moves, not even when the user sends a message.
const FOLLOW_DISTANCE = 40;

const WORKING = new Set<Session["state"]>(["starting", "running"]);

const NO_TASKS: ReadonlySet<string> = new Set();
const NO_STREAMS: Readonly<Record<string, string>> = {};
const NO_RUNS: BashRun[] = [];

// A message can be edited, rewound to or forked from when no turn runs, as the daemon
// allows (BUG-104, B59).
const AT_REST = new Set<Session["state"]>(["idle", "interrupted", "failed"]);

interface Props {
  session: Session;
  // Background tasks, so a group knows which of its calls still run.
  background: BackgroundSummary;
  // An event to scroll to and highlight once it is loaded, such as a search hit.
  focus?: number | null;
  // Whether the chat's history has been fetched: until then it is loading, and what was
  // there by then is not announced. A failed load offers Retry.
  history: HistoryStatus;
  onRetry: () => void;
  // A pixie's page, from a call to it.
  onOpenPixie: (id: string) => void;
  // A team's work in this chat, from a call to its leader; given only in a project chat,
  // where a call of a team's leader is the team's call (B70).
  onOpenWork?: ((who: WorkOf) => void) | undefined;
  // A chat, from a card a pixie posted (B41).
  onOpenChat: (sessionId: string) => void;
}

export function Transcript({
  session,
  background,
  focus = null,
  history,
  onRetry,
  onOpenPixie,
  onOpenWork,
  onOpenChat,
}: Props) {
  const loaded = history === "loaded";
  const { state, actions } = useStore();
  const events = state.transcripts[session.id];
  const live = state.live[session.id] ?? "";
  const thought = state.thoughts[session.id] ?? "";
  const agentLive = state.agentLive[session.id] ?? NO_STREAMS;
  const stopper = useStopTask(session.id);
  // `!` commands run since the last message (B59).
  const runs = state.bash[session.id] ?? NO_RUNS;
  // By value, so a new background summary with the same running tasks changes nothing.
  const runningKey = background.items
    .filter((i) => i.status === "running")
    .map((i) => i.id)
    .join("\n");
  const running = useMemo(
    () => new Set(runningKey === "" ? [] : runningKey.split("\n")),
    [runningKey],
  );
  const root = workRoot(session);
  // A call to a pixie shows as its row, matched by slug (B40).
  const pixies = useMemo(
    () => new Map(Object.values(state.pixies).map((p) => [p.slug, p])),
    [state.pixies],
  );
  // Built again only when the events, approvals, running tasks or pixies change (IMP-11).
  const items = useMemo(
    () => buildTranscript(events ?? [], state.approvals, root, running, pixies),
    [events, state.approvals, root, running, pixies],
  );
  const box = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const [away, setAway] = useState(false);
  // Bumped by "Jump to latest" to scroll down once more.
  const [jumps, setJumps] = useState(0);
  const working = WORKING.has(session.state);
  const start = useMemo(() => turnStart(events ?? []), [events]);
  const thinking = session.id in state.thinking;
  const focused = useRef<number | null>(null);
  const spoken = useAnnouncement(items, loaded);
  // The user message whose actions are open, being rewound to, or edited after files changed.
  const [sheet, setSheet] = useState<
    | { kind: "actions" | "rewind"; event: number }
    | { kind: "edit"; event: number; preview: RewindPreview }
    | null
  >(null);
  const { fill, ask } = usePrefill(draftKey({ session: session.id }));
  // Never in a pixie's chat: each run starts fresh, so earlier runs' checkpoints are gone.
  const onActions =
    AT_REST.has(session.state) && session.archived_at === null && session.pixie_id == null
      ? (event: number) => {
          setSheet({ kind: "actions", event });
        }
      : undefined;
  const close = () => {
    setSheet(null);
  };

  /** Rewinds; the conversation's message goes back in the composer. */
  const rewind = async (event: number, restore: Restore) => {
    const done = await actions.rewind(session.id, event, restore);
    if (done?.text != null && restore !== "code") {
      fill({ text: done.text, files: asDraftFiles(done.attachments) });
    }
  };

  /** Edit: rewinds the conversation, asking first whether files changed since go back too. */
  const edit = async (event: number) => {
    const preview = await actions.rewindPreview(session.id, event, "code", true);
    if (preview !== null && changesFiles(preview)) setSheet({ kind: "edit", event, preview });
    else await rewind(event, "conversation");
  };

  const fork = async (event: number) => {
    const forked = await actions.fork(session.id, event);
    if (forked !== null) onOpenChat(forked.session.id);
  };

  useLayoutEffect(() => {
    const el = box.current;
    if (el !== null && follow.current) el.scrollTop = el.scrollHeight;
  }, [items.length, live, agentLive, working, jumps, runs]);

  // Once the focused event is on screen, stop following and show it highlighted.
  useLayoutEffect(() => {
    const el = box.current;
    if (focus === null || focused.current === focus || el === null) return;
    const target = nearestItem(el, focus);
    if (target === null) return;
    focused.current = focus;
    follow.current = false;
    target.scrollIntoView({ block: "center" });
    target.classList.add("hit");
    target.addEventListener(
      "animationend",
      () => {
        target.classList.remove("hit");
      },
      { once: true },
    );
  }, [focus, items.length]);

  const calls: CallControls = { agentLive, running, stopper };

  const jump = () => {
    follow.current = true;
    setAway(false);
    setJumps((n) => n + 1);
  };

  return (
    <div className="ch-txw">
      <div
        className="ch-tx"
        ref={box}
        onScroll={(event) => {
          const el = event.currentTarget;
          follow.current = el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_DISTANCE;
          setAway(!follow.current);
        }}
      >
        {history === "loading" && items.length === 0 && <p className="note">Loading...</p>}
        {history === "failed" && (
          <div className="note">
            The messages could not be loaded.{" "}
            <button className="lnk" onClick={onRetry}>
              Retry
            </button>
          </div>
        )}
        {loaded && items.length === 0 && !working && (
          <div className="tx-empty">
            <Icon name="spark" />
            <b>No messages yet</b>
          </div>
        )}
        {/* Not a live region: it holds the ticking timer and streamed text. */}
        <div className="tx">
          <CallContext value={calls}>
            {items.map((item) => (
              <Item
                key={item.key}
                item={item}
                session={session}
                running={running}
                onActions={onActions}
                onOpenPixie={onOpenPixie}
                onOpenWork={onOpenWork}
                onOpenChat={onOpenChat}
              />
            ))}
          </CallContext>
          {live && <div className="m-a">{live}</div>}
          {runs.map((run) => (
            <LocalBash key={run.id} run={run} />
          ))}
          {working && <WorkingLine thinking={thinking} thought={thought} start={start} />}
        </div>
      </div>
      <p className="sr" role="status">
        {spoken}
      </p>
      {sheet?.kind === "actions" && (
        <MessageActions
          onClose={close}
          onEdit={() => void edit(sheet.event)}
          onRewind={() => {
            setSheet({ kind: "rewind", event: sheet.event });
          }}
          onFork={() => void fork(sheet.event)}
        />
      )}
      {sheet?.kind === "rewind" && (
        <RewindSheet
          sessionId={session.id}
          eventId={sheet.event}
          onClose={close}
          onRestore={(restore) => void rewind(sheet.event, restore)}
        />
      )}
      {sheet?.kind === "edit" && (
        <EditSheet
          preview={sheet.preview}
          onClose={close}
          onEdit={(restore) => void rewind(sheet.event, restore)}
        />
      )}
      {ask}
      {away && (
        <button className="jump gl" onClick={jump}>
          <Icon name="chev" />
          Jump to latest
        </button>
      )}
    </div>
  );
}

interface News {
  // Which item it is, and the event it came from, to tell new items from removed ones.
  id: string;
  event: number;
  text: string;
}

/** What a screen reader should hear about a finished item; null for the routine ones. */
function newsOf(item: TranscriptItem): string | null {
  switch (item.kind) {
    case "assistant":
    case "system":
    case "turn":
      return item.text;
    case "approval":
      return "Needs your approval";
    case "report":
      return item.title ?? "Chats finished";
    default:
      return null;
  }
}

function latestNews(items: TranscriptItem[]): News | null {
  for (const item of [...items].reverse()) {
    const text = newsOf(item);
    if (text !== null) {
      return { id: `${item.kind}:${item.key}`, event: Number.parseInt(item.key, 10), text };
    }
  }
  return null;
}

/**
 * The text for the chat's status region: the newest finished message, note, turn end or
 * approval once it arrives. Never the history, nor an older item that shows again as last
 * because a newer one went away.
 */
function useAnnouncement(items: TranscriptItem[], loaded: boolean): string {
  const [said, setSaid] = useState<News | null>(null);
  const latest = latestNews(items);
  if (loaded && said === null) {
    setSaid(latest === null ? { id: "", event: 0, text: "" } : { ...latest, text: "" });
  } else if (
    said !== null &&
    latest !== null &&
    latest.id !== said.id &&
    latest.event >= said.event
  ) {
    setSaid(latest);
  }
  return said?.text ?? "";
}

// The clock in whole seconds, so it reads the same within a second.
const seconds = () => Math.floor(Date.now() / 1000);
const noTicks = () => () => undefined;
function ticks(onTick: () => void): () => void {
  const timer = setInterval(onTick, 1000);
  return () => {
    clearInterval(timer);
  };
}

interface WorkingProps {
  thinking: boolean;
  // The thinking text streamed so far (B59).
  thought: string;
  start: string | null;
}

/**
 * "Working... 12s", ticking on its own so the transcript does not render every second.
 * It stops while the app is hidden and catches up when it shows again. While thinking
 * streams, it opens to the text, folded like a finished thought.
 */
function WorkingLine({ thinking, thought, start }: WorkingProps) {
  const visible = usePageVisible();
  const now = useSyncExternalStore(visible ? ticks : noTicks, seconds) * 1000;
  const line = (
    <span className="wline rglow">
      <Fireflies size={9} />
      <span className="glow">
        {thinking ? "Thinking..." : "Working..."}
        {start === null ? "" : ` ${elapsed(now - Date.parse(start))}`}
      </span>
    </span>
  );
  if (!thinking || !thought) return <div className="m-live">{line}</div>;
  return (
    <details className="m-live think">
      <summary>
        {line}
        <Icon name="chev" className="cv" />
      </summary>
      <div className="tht">{thought}</div>
    </details>
  );
}

/**
 * The item shown for an event: the last one at or before it, since a tool result shows
 * with its call.
 */
function nearestItem(box: HTMLElement, eventId: number): HTMLElement | null {
  let found: HTMLElement | null = null;
  for (const node of box.querySelectorAll<HTMLElement>("[data-ev]")) {
    if (Number(node.dataset.ev) > eventId) break;
    found = node;
  }
  return found;
}

interface ItemProps {
  item: TranscriptItem;
  session: Session;
  running: ReadonlySet<string>;
  onActions: ((eventId: number) => void) | undefined;
  onOpenPixie: (id: string) => void;
  onOpenWork: ((who: WorkOf) => void) | undefined;
  onOpenChat: (sessionId: string) => void;
}

function Item({
  item,
  session,
  running,
  onActions,
  onOpenPixie,
  onOpenWork,
  onOpenChat,
}: ItemProps) {
  const ev = item.key.replace(/\..*$/, "");
  switch (item.kind) {
    case "approval":
      return <InlineApproval approval={item.approval} session={session} />;
    case "pixie":
      return (
        <PixieCall
          item={item}
          ev={ev}
          sessionId={session.id}
          running={running}
          onOpenPixie={onOpenPixie}
          onOpenWork={onOpenWork}
        />
      );
    case "card":
      // Only a pixie's chat holds cards.
      return session.pixie_id == null ? null : (
        <PixieCard item={item} ev={ev} pixieId={session.pixie_id} onOpenChat={onOpenChat} />
      );
    default:
      return <MessageItem item={item} ev={ev} running={running} onActions={onActions} />;
  }
}

interface MessageActionsProps {
  onClose: () => void;
  onEdit: () => void;
  onRewind: () => void;
  onFork: () => void;
}

/** What can be done with one of the user's messages (B59), as in Claude Code. */
function MessageActions({ onClose, onEdit, onRewind, onFork }: MessageActionsProps) {
  const item = (label: string, run: () => void) => (
    <button
      className="asi"
      role="menuitem"
      onClick={() => {
        onClose();
        run();
      }}
    >
      {label}
    </button>
  );
  return (
    <ActionSheet label="Message" onClose={onClose}>
      {item("Edit", onEdit)}
      {item("Rewind...", onRewind)}
      {item("Fork from here", onFork)}
    </ActionSheet>
  );
}

// Pixie calls and cards show only in a Nest chat's transcript.
export type MessageEntry = Exclude<TranscriptItem, { kind: "approval" | "pixie" | "card" }>;

interface EntryProps {
  item: MessageEntry;
  ev?: string;
  // Calls whose background task still runs.
  running?: ReadonlySet<string>;
  // Offers editing, rewinding to or forking from a user message (by its event id).
  onActions?: ((eventId: number) => void) | undefined;
}

/** A message, tool call or note; read-only transcripts show only these. */
export function MessageItem({ item, ev, running = NO_TASKS, onActions }: EntryProps) {
  switch (item.kind) {
    case "user": {
      const bubble = (
        <div className="m-u" data-ev={ev}>
          <UserText text={item.text} />
          {item.attachments.length > 0 && <small>{item.attachments.join(", ")}</small>}
        </div>
      );
      const from = item.from === undefined ? null : <FromPixie id={item.from} />;
      if (onActions === undefined) {
        return (
          <>
            {from}
            {bubble}
          </>
        );
      }
      return (
        <>
          {from}
          <div className="m-ur">
            <button
              className="rwd"
              aria-label="Message actions"
              aria-haspopup="dialog"
              onClick={() => {
                onActions(Number(item.key));
              }}
            >
              <Icon name="dots" />
            </button>
            {bubble}
          </div>
        </>
      );
    }
    case "report":
      return (
        <div className="m-sys m-rep" data-ev={ev}>
          <b>{item.title ?? "Chats finished"}</b>
          <span>{item.text}</span>
        </div>
      );
    case "assistant":
      return (
        <div className="m-a" data-ev={ev}>
          {item.text}
        </div>
      );
    case "answer":
      return (
        <div className="m-ans" data-ev={ev}>
          <small>{item.question}</small>
          <div className="m-u">
            <UserText text={item.text} />
          </div>
        </div>
      );
    case "system":
      return (
        <div className="m-sys" data-ev={ev}>
          {item.text}
        </div>
      );
    case "hook":
      return <Hook item={item} ev={ev} />;
    case "bash":
      return (
        <Bash command={item.command} ev={ev}>
          {item.output && <Output text={item.output} />}
        </Bash>
      );
    case "turn":
      return (
        <div className="m-turn" data-ev={ev}>
          {item.text}
        </div>
      );
    case "thinking":
      return <Thinking item={item} ev={ev} />;
    case "tool":
      return item.diff === undefined ? (
        <Tool item={item} ev={ev} />
      ) : (
        <EditTool item={item} diff={item.diff} ev={ev} />
      );
    case "tools":
      return <ToolGroup items={item.items} ev={ev} running={running} />;
  }
}

interface PixieCallProps {
  item: PixieCallItem;
  ev: string;
  sessionId: string;
  running: ReadonlySet<string>;
  onOpenPixie: (id: string) => void;
  onOpenWork: ((who: WorkOf) => void) | undefined;
}

/**
 * A call to a pixie (B40): its mascot and name go to its page; the rest of the row opens
 * in place to the call's own messages, then its answer. A call to a team's leader is the
 * team's (B70): its grid of four and name in the leader's colour go to the team's work.
 */
function PixieCall({ item, ev, sessionId, running, onOpenPixie, onOpenWork }: PixieCallProps) {
  const [open, setOpen] = useState(false);
  const { state } = useStore();
  const { agentLive, stopper } = useContext(CallContext);
  const { pixie, call, steps } = item;
  const busy = call.result === null || running.has(call.id);
  const team = teamCall(state.teams, pixie.id, onOpenWork);
  const name = team?.team.name ?? pixie.name;
  return (
    <div className="tool pxcall" data-ev={ev}>
      <div className="pxch">
        {team === null ? (
          <button
            className="pxcn"
            aria-label={`Open ${pixie.name}`}
            onClick={() => {
              onOpenPixie(pixie.id);
            }}
          >
            <span aria-hidden="true">
              <Sprite
                mascot={pixie.mascot}
                color={pixie.color}
                size={18}
                working={busy}
                phaseKey={pixie.id}
              />
            </span>
            <span className="tn">{pixie.name}</span>
          </button>
        ) : (
          <button className="pxcn" aria-label={`Open team ${name}`} onClick={team.open}>
            <TeamFace
              members={teamFaces(team.team, state.pixies, state.pixieGroups[sessionId], busy)}
              pixies={state.pixies}
              className="pxteam"
              size={9}
            />
            <span className="tn pxtname" style={{ "--px": pixie.color } as CSSProperties}>
              {name}
            </span>
          </button>
        )}
        <button
          className="pxct"
          aria-expanded={open}
          onClick={() => {
            setOpen(!open);
          }}
        >
          {team !== null && busy && <span className="tr glow">working</span>}
          <span className="ta">{call.arg}</span>
          {!(team !== null && busy) && (
            <span className={busy ? "tr glow" : call.failed ? "tr bad" : "tr"}>
              {busy ? "running" : call.result}
            </span>
          )}
          <Icon name="chev" className="cv" />
        </button>
        {busy && <StopTask id={call.id} name={name} stopper={stopper} />}
      </div>
      {open && (
        <div className="tgl pxsteps" role="group" aria-label={`${name}'s steps`}>
          <SubSteps steps={steps} live={agentLive[call.id] ?? ""} />
          {busy || call.detail === null ? (
            <div className="pxans">{busy ? "running" : call.result}</div>
          ) : (
            <Output text={call.detail} />
          )}
        </div>
      )}
    </div>
  );
}

/** The team a call goes to when it calls the team's leader, where teams' calls show. */
function teamCall(
  teams: Record<string, PixieTeam>,
  pixieId: string,
  onOpenWork: ((who: WorkOf) => void) | undefined,
): { team: PixieTeam; open: () => void } | null {
  if (onOpenWork === undefined) return null;
  const team = Object.values(teams).find((t) => t.leader_id === pixieId);
  return team === undefined
    ? null
    : {
        team,
        open: () => {
          onOpenWork({ team: team.id });
        },
      };
}

/**
 * A team's members for its grid: while the call runs its leader hops, and each member the
 * chat's group says is at work; at rest once it answered.
 */
function teamFaces(
  team: PixieTeam,
  pixies: Record<string, Pixie>,
  group: GroupEntry[] | undefined,
  busy: boolean,
): TeamMember[] {
  const entry = group?.find((e) => e.team_id === team.id);
  return Object.values(pixies)
    .filter((p) => p.team_id === team.id)
    .map((p) => {
      const leader = p.id === team.leader_id;
      const working = entry?.members.some((m) => m.pixie_id === p.id && m.state === "running");
      return { pixie_id: p.id, leader, state: busy && (leader || working) ? "running" : null };
    });
}

/** "from Tester" with its mascot, above a message a pixie sent into this chat (B41). */
function FromPixie({ id }: { id: string }) {
  const { state } = useStore();
  const pixie = state.pixies[id];
  return (
    <div className="m-from">
      {pixie !== undefined && (
        <span aria-hidden="true">
          <Sprite mascot={pixie.mascot} color={pixie.color} size={14} />
        </span>
      )}
      <span>{pixie === undefined ? "from a pixie" : `from ${pixie.name}`}</span>
    </div>
  );
}

/** A sent message, its @ mentions of known pixies and teams in the pixie's colour (B40). */
function UserText({ text }: { text: string }) {
  const { state } = useStore();
  const colors = useMemo(
    () => mentionColors(state.pixies, state.teams),
    [state.pixies, state.teams],
  );
  return mentionParts(text, colors).map((part, index) =>
    part.color === null ? (
      part.text
    ) : (
      <span key={index} className="mention" style={{ "--px": part.color } as CSSProperties}>
        {part.text}
      </span>
    ),
  );
}

/** "Thought for 8s", opening to the thinking; nothing to open when the engine left it out. */
function Thinking({ item, ev }: { item: ThinkingItem; ev?: string | undefined }) {
  const label = thoughtLabel(item.ms);
  if (!item.text.trim()) {
    return (
      <div className="think" data-ev={ev}>
        <span className="thl">{label}</span>
      </div>
    );
  }
  return (
    <details className="think" data-ev={ev}>
      <summary>
        <span className="thl">{label}</span>
        <Icon name="chev" className="cv" />
      </summary>
      <div className="tht">{item.text}</div>
    </details>
  );
}

/** A subagent's thinking, text and tools as lines, then the text it is writing now. */
function SubSteps({ steps, live }: { steps: SubStep[]; live: string }) {
  return (
    <>
      {steps.map((step) =>
        step.kind === "images" ? (
          <ResultImages key={step.key} images={step.images} from="a subagent" />
        ) : (
          <div key={step.key} className={STEP_CLASSES[step.kind]}>
            {step.text}
          </div>
        ),
      )}
      {live && <div className="pxtext live">{live}</div>}
    </>
  );
}

const STEP_CLASSES: Record<Exclude<SubStep["kind"], "images">, string> = {
  text: "pxtext",
  call: "pxstep",
  thinking: "pxthink",
};

function Tool({ item, ev }: { item: ToolItem; ev?: string | undefined }) {
  const { agentLive, running, stopper } = useContext(CallContext);
  const agent = toolKind(item.name) === "agent";
  const busy = agent && (item.result === null || running.has(item.id));
  const steps = item.steps ?? [];
  const live = agent ? (agentLive[item.id] ?? "") : "";
  const summary = (
    <>
      <Icon name={toolIcon(item.name)} />
      <span className="tn">{item.name}</span>
      <span className="ta">{item.arg}</span>
      <span className={item.failed ? "tr bad" : "tr"}>{item.result ?? "running"}</span>
      {busy && <StopTask id={item.id} name={item.arg || item.name} stopper={stopper} />}
    </>
  );
  const images = item.images && <ResultImages images={item.images} from={item.name} />;
  if (item.detail === null && steps.length === 0 && !live) {
    return (
      <>
        <div className="tool" data-ev={ev}>
          <div className="tsum">{summary}</div>
        </div>
        {images}
      </>
    );
  }
  const row = (
    <details className="tool" data-ev={ev}>
      <summary>
        {summary}
        <Icon name="chev" className="cv" />
      </summary>
      {(steps.length > 0 || live) && (
        <div className="pxsteps">
          <SubSteps steps={steps} live={live} />
        </div>
      )}
      {item.detail !== null && <Output text={item.detail} />}
    </details>
  );
  return (
    <>
      {row}
      {images}
    </>
  );
}

// An edit shows this many lines of its diff until opened further.
const DIFF_PREVIEW = 8;
const SIGNS: Record<DiffLine["kind"], string> = { add: "+", del: "-", ctx: " ", gap: "…" };
const LINE_CLASSES: Record<DiffLine["kind"], string> = {
  add: "dl a",
  del: "dl d",
  ctx: "dl",
  gap: "dl g",
};

interface EditProps {
  item: ToolItem;
  diff: EditDiff;
  ev?: string | undefined;
}

/**
 * An edit as Claude's apps show it (B59): the file with what it adds and removes, and the
 * changed lines in red and green, folded to the first lines. A failure says why.
 */
function EditTool({ item, diff, ev }: EditProps) {
  const [all, setAll] = useState(false);
  const shown = all ? diff.lines : diff.lines.slice(0, DIFF_PREVIEW);
  const counts = `${String(diff.added)} added, ${String(diff.removed)} removed`;
  const status = item.failed ? "failed" : item.result === null ? "running" : null;
  return (
    <div className="tool tedit" data-ev={ev}>
      <div className="tsum">
        <Icon name={toolIcon(item.name)} />
        <span className="tn">{item.name}</span>
        <span className="ta">{item.arg}</span>
        <span className="ds" aria-label={counts}>
          <span className="a">{`+${String(diff.added)}`}</span>{" "}
          <span className="d">{`-${String(diff.removed)}`}</span>
        </span>
        {status !== null && <span className={item.failed ? "tr bad" : "tr"}>{status}</span>}
      </div>
      <div className="tdiff" role="group" aria-label={`Changes to ${item.arg}`}>
        {shown.map((line, index) => (
          <div key={index} className={LINE_CLASSES[line.kind]}>
            <b>{SIGNS[line.kind]}</b>
            <code>{line.text}</code>
          </div>
        ))}
      </div>
      {diff.lines.length > DIFF_PREVIEW && (
        <button
          className="lnk tmore"
          onClick={() => {
            setAll(!all);
          }}
        >
          {all ? "Show less" : `Show all ${String(diff.lines.length)} lines`}
        </button>
      )}
      {item.failed && item.detail !== null && <Output text={item.detail} />}
    </div>
  );
}

/** A tool's output: its first lines, and all of it on request (B59). */
function Output({ text }: { text: string }) {
  const [all, setAll] = useState(false);
  const preview = useMemo(() => outputPreview(text), [text]);
  if (!preview.cut) return <pre>{text}</pre>;
  const more = preview.lines > 1 ? `Show all ${String(preview.lines)} lines` : "Show all";
  return (
    <div className="tout">
      <pre>{all ? text : preview.text}</pre>
      <button
        className="lnk"
        onClick={() => {
          setAll(!all);
        }}
      >
        {all ? "Show less" : more}
      </button>
    </div>
  );
}

interface BashProps {
  command: string;
  ev?: string | undefined;
  children: ReactNode;
}

/** A `!` command as Claude Code's bash mode shows it (B59), with what it printed. */
function Bash({ command, ev, children }: BashProps) {
  return (
    <div className="bash" data-ev={ev}>
      <code className="bcmd">{`! ${command}`}</code>
      {children}
    </div>
  );
}

/** How a command ended, when not plainly. */
function ending({ exit_code, timed_out, truncated }: ShellResult): string[] {
  return [
    ...(timed_out ? ["timed out after 2 minutes"] : []),
    ...(exit_code !== null && exit_code !== 0 ? [`exit ${String(exit_code)}`] : []),
    ...(truncated ? ["output cut"] : []),
  ];
}

/** A command run here that no message has carried to Claude yet. */
function LocalBash({ run }: { run: BashRun }) {
  const { result, error } = run;
  return (
    <Bash command={run.command}>
      {result === null && error === null && (
        <span className="bnote" role="status">
          <Fireflies size={9} />
          Running
        </span>
      )}
      {result?.output && <Output text={result.output} />}
      {result !== null &&
        ending(result).map((line) => (
          <span key={line} className="bnote">
            {line}
          </span>
        ))}
      {error !== null && <span className="bnote bad">{error}</span>}
    </Bash>
  );
}

/** What a hook said, as a quiet line like Claude Code's; a failure shows its output. */
function Hook({ item, ev }: { item: HookItem; ev?: string | undefined }) {
  const className = item.tone === "error" ? "m-hook bad" : "m-hook";
  if (item.detail === null) {
    return (
      <div className={className} data-ev={ev}>
        {item.text}
      </div>
    );
  }
  if (item.tone === "error") {
    return (
      <div className={className} data-ev={ev}>
        <span>{item.text}</span>
        <pre>{item.detail}</pre>
      </div>
    );
  }
  return (
    <details className={className} data-ev={ev}>
      <summary>
        <span>{item.text}</span>
        <Icon name="chev" className="cv" />
      </summary>
      <pre>{item.detail}</pre>
    </details>
  );
}

interface GroupProps {
  items: (ToolItem | ThinkingItem)[];
  ev?: string | undefined;
  running: ReadonlySet<string>;
}

/** "Ran 3 commands, read 2 files", opening to the calls as they show on their own. */
function ToolGroup({ items, ev, running }: GroupProps) {
  const tools = items.filter((item): item is ToolItem => item.kind === "tool");
  const summary = summarizeTools(tools, running);
  return (
    <details className="tool tgroup" data-ev={ev}>
      <summary>
        <Icon name="list" />
        <span className={summary.running ? "tg glow" : "tg"}>{summary.text}</span>
        {summary.failed > 0 && <span className="tr bad">{`${String(summary.failed)} failed`}</span>}
        <Icon name="chev" className="cv" />
      </summary>
      <div className="tgl">
        {items.map((item) => (
          <MessageItem key={item.key} item={item} />
        ))}
      </div>
    </details>
  );
}
