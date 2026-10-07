import { useLayoutEffect, useRef, useState } from "react";
import type { QueuedMessage, Session, TrackedAgent } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { buildTranscript, type TranscriptItem } from "../../transcript/build.ts";
import { Icon } from "../../ui/Icon.tsx";
import { toolIcon } from "../../ui/toolIcon.ts";
import { workRoot } from "../approvals/hooks.ts";
import { InlineApproval } from "./InlineApproval.tsx";

// Within this many pixels of the bottom, new output is followed. Anywhere else the
// reading position never moves, not even when the user sends a message.
const FOLLOW_DISTANCE = 40;

const WORKING = new Set<Session["state"]>(["starting", "running"]);

interface Props {
  session: Session;
  agents: TrackedAgent[];
  // An event to scroll to and highlight once it is loaded, such as a search hit.
  focus?: number | null;
}

export function Transcript({ session, agents, focus = null }: Props) {
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
  const main = agents.find((a) => a.name === "main");
  const focused = useRef<number | null>(null);

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
        <div className="tx" aria-live="polite">
          {items.map((item) => (
            <Item key={item.key} item={item} session={session} />
          ))}
          {live && <div className="m-a">{live}</div>}
          {working && (
            <div className="m-live">
              <span className="dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              <span className="mono">{main?.activity ?? "Thinking"}</span>
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
      {away && (
        <button className="jump gl" onClick={jump}>
          <Icon name="chev" />
          Jump to latest
        </button>
      )}
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

function Item({ item, session }: { item: TranscriptItem; session: Session }) {
  return item.kind === "approval" ? (
    <InlineApproval approval={item.approval} session={session} />
  ) : (
    <MessageItem item={item} ev={item.key.replace(/\..*$/, "")} />
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

/** A message, tool call or note; read-only transcripts show only these. */
export function MessageItem({ item, ev }: { item: MessageEntry; ev?: string }) {
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
    case "tool": {
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
  }
}
