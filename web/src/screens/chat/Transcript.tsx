import { useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { BackgroundSummary, QueuedMessage, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import type { HistoryStatus } from "../../store/state.ts";
import { elapsed, summarizeTools, thoughtLabel } from "../../transcript/activity.ts";
import {
  buildTranscript,
  turnStart,
  type ThinkingItem,
  type ToolItem,
  type TranscriptItem,
} from "../../transcript/build.ts";
import { Icon } from "../../ui/Icon.tsx";
import { toolIcon } from "../../ui/toolIcon.ts";
import { usePageVisible } from "../../ui/visible.ts";
import { workRoot } from "../approvals/hooks.ts";
import { InlineApproval } from "./InlineApproval.tsx";
import { RewindSheet } from "./RewindSheet.tsx";

// Within this many pixels of the bottom, new output is followed. Anywhere else the
// reading position never moves, not even when the user sends a message.
const FOLLOW_DISTANCE = 40;

const WORKING = new Set<Session["state"]>(["starting", "running"]);

const NO_TASKS: ReadonlySet<string> = new Set();

// Files can be restored when no turn runs, as the daemon allows (BUG-104).
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
}

export function Transcript({ session, background, focus = null, history, onRetry }: Props) {
  const loaded = history === "loaded";
  const { state, actions } = useStore();
  const events = state.transcripts[session.id];
  const live = state.live[session.id] ?? "";
  const queued = state.queued[session.id] ?? [];
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
  // Built again only when the events, approvals or running tasks change (IMP-11).
  const items = useMemo(
    () => buildTranscript(events ?? [], state.approvals, root, running),
    [events, state.approvals, root, running],
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
  // The user message whose files are being restored to before it.
  const [rewinding, setRewinding] = useState<number | null>(null);
  // Never in a pixie's chat: each run starts fresh, so earlier runs' checkpoints are gone.
  const onRewind =
    AT_REST.has(session.state) && session.archived_at === null && session.pixie_id == null
      ? setRewinding
      : undefined;

  useLayoutEffect(() => {
    const el = box.current;
    if (el !== null && follow.current) el.scrollTop = el.scrollHeight;
  }, [items.length, live, working, jumps, queued.length]);

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
          {items.map((item) => (
            <Item
              key={item.key}
              item={item}
              session={session}
              running={running}
              onRewind={onRewind}
            />
          ))}
          {live && <div className="m-a">{live}</div>}
          {working && <WorkingLine thinking={thinking} start={start} />}
          {queued.map((message) => (
            <Queued
              key={message.id}
              message={message}
              onCancel={() => void actions.cancelQueued(session.id, message.id)}
            />
          ))}
        </div>
      </div>
      <p className="sr" role="status">
        {spoken}
      </p>
      {rewinding !== null && (
        <RewindSheet
          sessionId={session.id}
          eventId={rewinding}
          onClose={() => {
            setRewinding(null);
          }}
        />
      )}
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

/**
 * "Working... 12s", ticking on its own so the transcript does not render every second.
 * It stops while the app is hidden and catches up when it shows again.
 */
function WorkingLine({ thinking, start }: { thinking: boolean; start: string | null }) {
  const visible = usePageVisible();
  const now = useSyncExternalStore(visible ? ticks : noTicks, seconds) * 1000;
  return (
    <div className="m-live">
      <span className="glow">
        {thinking ? "Thinking..." : "Working..."}
        {start === null ? "" : ` ${elapsed(now - Date.parse(start))}`}
      </span>
    </div>
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
  onRewind: ((eventId: number) => void) | undefined;
}

function Item({ item, session, running, onRewind }: ItemProps) {
  return item.kind === "approval" ? (
    <InlineApproval approval={item.approval} session={session} />
  ) : (
    <MessageItem
      item={item}
      ev={item.key.replace(/\..*$/, "")}
      running={running}
      onRewind={onRewind}
    />
  );
}

/** A message waiting for the running turn to end, dimmed until it is sent. */
function Queued({ message, onCancel }: { message: QueuedMessage; onCancel: () => void }) {
  return (
    <div className="m-u queued">
      <span className="qh">
        Queued
        <button aria-label="Cancel queued message" onClick={onCancel}>
          <Icon name="x" />
        </button>
      </span>
      {message.text}
      {message.attachments.length > 0 && (
        <small>{message.attachments.map((a) => a.filename).join(", ")}</small>
      )}
    </div>
  );
}

export type MessageEntry = Exclude<TranscriptItem, { kind: "approval" }>;

interface EntryProps {
  item: MessageEntry;
  ev?: string;
  // Calls whose background task still runs.
  running?: ReadonlySet<string>;
  // Offers restoring files to before a user message (by its event id).
  onRewind?: ((eventId: number) => void) | undefined;
}

/** A message, tool call or note; read-only transcripts show only these. */
export function MessageItem({ item, ev, running = NO_TASKS, onRewind }: EntryProps) {
  switch (item.kind) {
    case "user": {
      const bubble = (
        <div className="m-u" data-ev={ev}>
          {item.text}
          {item.attachments.length > 0 && <small>{item.attachments.join(", ")}</small>}
        </div>
      );
      if (onRewind === undefined) return bubble;
      return (
        <div className="m-ur">
          <button
            className="rwd"
            aria-label="Restore files to before this message"
            aria-haspopup="dialog"
            onClick={() => {
              onRewind(Number(item.key));
            }}
          >
            <Icon name="restore" />
          </button>
          {bubble}
        </div>
      );
    }
    case "assistant":
      return (
        <div className="m-a" data-ev={ev}>
          {item.text}
        </div>
      );
    case "system":
      return (
        <div className="m-sys" data-ev={ev}>
          {item.text}
        </div>
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
      return <Tool item={item} ev={ev} />;
    case "tools":
      return <ToolGroup items={item.items} ev={ev} running={running} />;
  }
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

function Tool({ item, ev }: { item: ToolItem; ev?: string | undefined }) {
  const summary = (
    <>
      <Icon name={toolIcon(item.name)} />
      <span className="tn">{item.name}</span>
      <span className="ta">{item.arg}</span>
      <span className={item.failed ? "tr bad" : "tr"}>{item.result ?? "running"}</span>
    </>
  );
  if (item.detail === null) {
    return (
      <div className="tool" data-ev={ev}>
        <div className="tsum">{summary}</div>
      </div>
    );
  }
  return (
    <details className="tool" data-ev={ev}>
      <summary>
        {summary}
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
