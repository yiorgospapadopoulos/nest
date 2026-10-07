import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { BackgroundSummary, QueuedMessage, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
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
import { workRoot } from "../approvals/hooks.ts";
import { InlineApproval } from "./InlineApproval.tsx";

// Within this many pixels of the bottom, new output is followed. Anywhere else the
// reading position never moves, not even when the user sends a message.
const FOLLOW_DISTANCE = 40;

const WORKING = new Set<Session["state"]>(["starting", "running"]);

const NO_TASKS: ReadonlySet<string> = new Set();

interface Props {
  session: Session;
  // Background tasks, so a group knows which of its calls still run.
  background: BackgroundSummary;
  // An event to scroll to and highlight once it is loaded, such as a search hit.
  focus?: number | null;
  // Whether the chat's history has been fetched; what was there by then is not announced.
  loaded: boolean;
}

export function Transcript({ session, background, focus = null, loaded }: Props) {
  const { state, actions } = useStore();
  const events = state.transcripts[session.id];
  const live = state.live[session.id] ?? "";
  const queued = state.queued[session.id] ?? [];
  const items = buildTranscript(events ?? [], state.approvals, workRoot(session));
  const box = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const [away, setAway] = useState(false);
  // Bumped by "Jump to latest" to scroll down once more.
  const [jumps, setJumps] = useState(0);
  const working = WORKING.has(session.state);
  const now = useNow(working);
  const start = turnStart(events ?? []);
  const thinking = session.id in state.thinking;
  const running = new Set(background.items.filter((i) => i.status === "running").map((i) => i.id));
  const focused = useRef<number | null>(null);
  const spoken = useAnnouncement(items, loaded);

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
        {events === undefined && <p className="note">Loading...</p>}
        {events !== undefined && items.length === 0 && !working && (
          <div className="tx-empty">
            <Icon name="spark" />
            <b>No messages yet</b>
          </div>
        )}
        {/* Not a live region: it holds the ticking timer and streamed text. */}
        <div className="tx">
          {items.map((item) => (
            <Item key={item.key} item={item} session={session} running={running} />
          ))}
          {live && <div className="m-a">{live}</div>}
          {working && (
            <div className="m-live">
              <span className="glow">
                {thinking ? "Thinking..." : "Working..."}
                {start === null ? "" : ` ${elapsed(now - Date.parse(start))}`}
              </span>
            </div>
          )}
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

/** The time, ticking every second while `ticking`. */
function useNow(ticking: boolean): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!ticking) return;
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => {
      clearInterval(timer);
    };
  }, [ticking]);
  return now;
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
}

function Item({ item, session, running }: ItemProps) {
  return item.kind === "approval" ? (
    <InlineApproval approval={item.approval} session={session} />
  ) : (
    <MessageItem item={item} ev={item.key.replace(/\..*$/, "")} running={running} />
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
}

/** A message, tool call or note; read-only transcripts show only these. */
export function MessageItem({ item, ev, running = NO_TASKS }: EntryProps) {
  switch (item.kind) {
    case "user":
      return (
        <div className="m-u" data-ev={ev}>
          {item.text}
          {item.attachments.length > 0 && <small>{item.attachments.join(", ")}</small>}
        </div>
      );
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
