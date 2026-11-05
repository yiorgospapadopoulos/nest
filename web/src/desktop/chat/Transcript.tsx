// A chat's transcript: following new content while at the
// bottom, Jump to latest once the reader scrolled up, a search hit scrolled to and glowing,
// and a long chat drawing only the rows near the screen (B117). Rows that open keep their
// open state outside the rows, so scrolling them away and back keeps them as left.
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { BackgroundSummary, Restore, Session } from "../../api/types.ts";
import { reviewWaitingLine } from "../../transcript/github.ts";
import { ScrollFollow } from "../../screens/chat/scrollFollow.ts";
import { useJumpOnSend } from "../../screens/chat/useJumpOnSend.ts";
import { useStopTask } from "../../screens/chat/useStopTask.ts";
import { itemIndexAt, nearestItem, VIRTUAL_FROM } from "../../screens/chat/virtualRows.ts";
import { workRoot } from "../../screens/approvals/hooks.ts";
import { asDraftFiles } from "../../store/actions.ts";
import { useStore } from "../../store/context.ts";
import { pendingFor, supportsFeature } from "../../store/selectors.ts";
import { downBody, downTitle, startLabel } from "../../store/local.ts";
import { draftKey, type BashRun, type HistoryStatus } from "../../store/state.ts";
import { elapsed } from "../../transcript/activity.ts";
import { buildTranscript, turnStart, type TranscriptItem } from "../../transcript/build.ts";
import { usePageVisible } from "../../ui/visible.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Markdown } from "../../ui/Markdown.tsx";
import { Button } from "../ui/controls.tsx";
import { onRewindLast } from "./composerFocus.ts";
import { groupRow, hoverTurn, setOpen, turnEnds, useOpen } from "./expanded.ts";
import { Disclosure, Glyph } from "./glyphs.tsx";
import { RewindSheet } from "./RewindSheet.tsx";
import { BashRow, TranscriptRow } from "./Rows.tsx";
import { RowsContext, type ChatRows, type RowsHost } from "./rowsContext.ts";
import { usePrefill } from "./usePrefill.tsx";
import { VirtualList } from "./VirtualList.tsx";
import { ChangeModelMenu } from "./Composer.tsx";

const WORKING = new Set<Session["state"]>(["starting", "running"]);
// A message can be edited, rewound to or forked from when no turn runs (BUG-104, B59).
const AT_REST = new Set<Session["state"]>(["idle", "interrupted", "failed"]);
const NO_STREAMS: Readonly<Record<string, string>> = {};
const NO_RUNS: BashRun[] = [];

export interface TranscriptNav {
  openPixie: (id: string) => void;
  openTeamWork: ((team: string) => void) | null;
  openPixieWork: ((pixie: string) => void) | null;
  openChat: (id: string) => void;
  // The Mac app around a pane takes what rows leave to it.
  host?: RowsHost;
}

interface Props {
  session: Session;
  background: BackgroundSummary;
  // An event to scroll to and let glow once it is loaded, such as a search hit.
  focus: number | null;
  history: HistoryStatus;
  onRetry: () => void;
  // Another pane has the focus (B93): losing it jumps to the latest.
  dimmed: boolean;
  nav: TranscriptNav;
  // Bars over the transcript's bottom edge, which the list scrolls under.
  bottom?: ReactNode;
  // `!` commands kept outside the store, by the Mac app around a pane.
  bash?: BashRun[];
}

/** Centres a search hit and lets it glow until its animation ends. */
function showHit(target: HTMLElement): void {
  target.scrollIntoView({ block: "center" });
  target.classList.add("dc-hit");
  target.addEventListener(
    "animationend",
    () => {
      target.classList.remove("dc-hit");
    },
    { once: true },
  );
}

type Rewinding = { event: number; purpose: "rewind" | "edit" } | null;

export function Transcript({
  session,
  background,
  focus,
  history,
  onRetry,
  dimmed,
  nav,
  bottom,
  bash,
}: Props) {
  const { state, actions } = useStore();
  const id = session.id;
  const events = state.transcripts[id];
  const live = state.live[id] ?? "";
  const thought = state.thoughts[id] ?? "";
  const agentLive = state.agentLive[id] ?? NO_STREAMS;
  const runs = bash ?? state.bash[id] ?? NO_RUNS;
  const stopper = useStopTask(id);
  const runningKey = background.items
    .filter((i) => i.status === "running")
    .map((i) => i.id)
    .join("\n");
  const running = useMemo(
    () => new Set(runningKey === "" ? [] : runningKey.split("\n")),
    [runningKey],
  );
  const root = workRoot(session);
  const pixies = useMemo(
    () => new Map(Object.values(state.pixies).map((p) => [p.slug, p])),
    [state.pixies],
  );
  const items = useMemo(
    () => buildTranscript(events ?? [], state.approvals, root, running, pixies),
    [events, state.approvals, root, running, pixies],
  );
  // A report can take the row of the message it hides, so the count stays.
  const lastItem = items.at(-1)?.key;
  const ends = useMemo(() => turnEnds(items), [items]);
  const box = useRef<HTMLDivElement>(null);
  const follow = useRef(new ScrollFollow());
  const [away, setAway] = useState(false);
  const [jumps, setJumps] = useState(0);
  const working = WORKING.has(session.state);
  const start = useMemo(() => turnStart(events ?? []), [events]);
  const thinking = id in state.thinking;
  const focused = useRef<number | null>(null);
  const [windowed, setWindowed] = useState(false);
  const virtual = windowed || (items.length >= VIRTUAL_FROM && !away);
  if (virtual && !windowed) setWindowed(true);
  const [rewinding, setRewinding] = useState<Rewinding>(null);
  const draft = draftKey({ session: id });
  const { fill, ask } = usePrefill(draft);
  const loaded = history === "loaded";

  // A pane that loses the focus to another goes back to the latest and follows (B93).
  const [wasDimmed, setWasDimmed] = useState(dimmed);
  const [dimJumps, setDimJumps] = useState(0);
  if (wasDimmed !== dimmed) {
    setWasDimmed(dimmed);
    if (dimmed) {
      setAway(false);
      setDimJumps((n) => n + 1);
    }
  }
  useLayoutEffect(() => {
    if (dimJumps === 0) return;
    follow.current.jumpToLatest();
    const el = box.current;
    if (el !== null) el.scrollTop = el.scrollHeight;
  }, [dimJumps]);

  // Esc Esc in the composer rewinds to before the last message (B59).
  const lastMessage = useMemo(() => {
    for (const item of [...items].reverse()) if (item.kind === "user") return Number(item.key);
    return null;
  }, [items]);

  useLayoutEffect(() => {
    const el = box.current;
    if (el !== null && follow.current.contentArrived()) el.scrollTop = el.scrollHeight;
  }, [items.length, lastItem, live, agentLive, working, jumps, runs]);

  // A hit inside a collapsed group of tool calls opens the group first; a tool result's
  // event shows with its call, so the hit's item is the last at or before it.
  useLayoutEffect(() => {
    if (focus === null) return;
    const index = itemIndexAt(items, focus);
    const item = index === null ? undefined : items[index];
    if (item?.kind === "tools") setOpen(id, groupRow(item.key), true);
  }, [focus, items, id]);

  // Asked again later, the same event scrolls and glows again.
  useLayoutEffect(() => {
    if (focus === null) focused.current = null;
  }, [focus]);

  useLayoutEffect(() => {
    const el = box.current;
    if (virtual || focus === null || focused.current === focus || el === null) return;
    const target = nearestItem(el, focus);
    if (target === null) return;
    focused.current = focus;
    follow.current.hold();
    setAway(true);
    showHit(target);
  }, [focus, items.length, virtual]);

  const canRewind = supportsFeature(state, "rewind", session.provider);
  const canFork = supportsFeature(state, "fork", session.provider);
  const atRest =
    AT_REST.has(session.state) && session.archived_at === null && session.pixie_id == null;
  useEffect(
    () =>
      onRewindLast(id, () => {
        if (atRest && canRewind && lastMessage !== null) {
          setRewinding({ event: lastMessage, purpose: "rewind" });
        }
      }),
    [id, atRest, canRewind, lastMessage],
  );

  const rewind = async (event: number, restore: Restore): Promise<boolean> => {
    const done = await actions.rewind(id, event, restore);
    if (done === null) return false;
    if (done.text != null && restore !== "code") {
      fill({ text: done.text, files: asDraftFiles(done.attachments) });
    }
    return true;
  };
  const edit = async (event: number) => {
    const preview = await actions.rewindPreview(id, event, "code", true);
    const files =
      preview?.can_rewind === true &&
      (Array.isArray(preview.files_changed)
        ? preview.files_changed.length
        : preview.files_changed) > 0;
    if (files) setRewinding({ event, purpose: "edit" });
    else await rewind(event, "conversation");
  };
  const fork = async (event: number) => {
    const forked = await actions.fork(id, event);
    if (forked !== null) nav.openChat(forked.session.id);
  };

  const { host } = nav;
  const local = {
    edit: (event: number) => () => void edit(event),
    rewind: (event: number) => () => {
      setRewinding({ event, purpose: "rewind" });
    },
    fork: (event: number) => () => void fork(event),
  };
  const act = (action: "edit" | "rewind" | "fork", event: number) =>
    host === undefined
      ? local[action](event)
      : () => {
          host.messageAction(action, event);
        };

  const rows: ChatRows = {
    chat: id,
    session,
    running,
    agentLive,
    stopper,
    openPixie: nav.openPixie,
    openTeamWork: nav.openTeamWork,
    openPixieWork: nav.openPixieWork,
    openChat: nav.openChat,
    messageActions:
      atRest && (canRewind || canFork)
        ? (event) => ({
            edit: canRewind ? act("edit", event) : null,
            rewind: canRewind ? act("rewind", event) : null,
            fork: canFork ? act("fork", event) : null,
          })
        : null,
    terminalPane: id,
    host: host ?? null,
  };

  const jump = () => {
    follow.current.jumpToLatest();
    setAway(false);
    setJumps((n) => n + 1);
  };
  useJumpOnSend(items, state.queued[id]?.length ?? 0, loaded, jump);

  const renderItem = (item: TranscriptItem) => (
    <div
      className="dc-item"
      onMouseEnter={() => {
        hoverTurn(ends.get(item.key) ?? null);
      }}
    >
      <TranscriptRow item={item} />
    </div>
  );

  const review = pendingFor(state, id).find((a) => a.kind === "review_comments");
  const down = state.local.failures[id];

  return (
    <RowsContext value={rows}>
      <div className="dc-txw">
        <div
          ref={box}
          className={virtual ? "dc-tx virt" : "dc-tx"}
          onMouseLeave={() => {
            hoverTurn(null);
          }}
          onScroll={(event) => {
            const el = event.currentTarget;
            const metrics = {
              offset: el.scrollTop,
              viewport: el.clientHeight,
              content: el.scrollHeight,
            };
            if (follow.current.update(metrics)) el.scrollTop = el.scrollHeight;
            setAway(follow.current.showsJump);
          }}
        >
          <div className="dc-txin">
            {virtual ? (
              <VirtualList
                items={items}
                follow={follow}
                focus={focus}
                focused={focused}
                onHit={showHit}
                renderItem={renderItem}
              />
            ) : (
              items.map((item) => <div key={item.key}>{renderItem(item)}</div>)
            )}
            {live !== "" && (
              <div className="dc-item">
                <div className="dc-md">
                  <Markdown text={live} />
                </div>
              </div>
            )}
            {review !== undefined && (
              <p className="dc-rvwait">
                <span className="dc-dot wait" />
                {reviewWaitingLine(review)}
              </p>
            )}
            {working && live === "" && (
              <WorkingLine chat={id} thinking={thinking} thought={thought} start={start} />
            )}
            {runs.map((run) => (
              <BashRow
                key={run.id}
                id={`bash-${String(run.id)}`}
                command={run.command}
                output={run.result?.output ?? ""}
                notes={
                  run.result === null
                    ? []
                    : [
                        ...(run.result.timed_out ? ["timed out after 2 minutes"] : []),
                        ...(run.result.exit_code !== null && run.result.exit_code !== 0
                          ? [`exit ${String(run.result.exit_code)}`]
                          : []),
                        ...(run.result.truncated ? ["output cut"] : []),
                      ]
                }
                running={run.result === null && run.error === null}
                failure={run.error}
              />
            ))}
            {down?.code === "local_server_down" && (
              <div className="dc-down" role="group" aria-label={downTitle(down)}>
                <b>{downTitle(down)}</b>
                <p>{downBody(down)}</p>
                <div className="dc-down-b">
                  {down.start !== null && (
                    <Button
                      disabled={state.local.starting.includes(down.start)}
                      onClick={() => {
                        if (down.start !== null) void actions.startLocalServer(down.start);
                      }}
                    >
                      {startLabel(down.start)}
                    </Button>
                  )}
                  <ChangeModelMenu session={session} />
                </div>
              </div>
            )}
            {history === "loading" && items.length === 0 && (
              <p className="dc-empty">
                <Fireflies size={11} />
              </p>
            )}
            {history === "failed" && (
              <div className="dc-sys">
                Could not load this chat.{" "}
                <button className="dc-linkbtn" onClick={onRetry}>
                  Retry
                </button>
              </div>
            )}
            {loaded && items.length === 0 && !working && <p className="dc-empty">New chat</p>}
          </div>
        </div>
        {away && (
          <button className="dc-jump" onClick={jump}>
            <Glyph name="arrowDown" size={11} />
            Jump to latest
          </button>
        )}
      </div>
      {bottom !== undefined && <div className="dc-txbottom">{bottom}</div>}
      {rewinding !== null && (
        <RewindSheet
          sessionId={id}
          event={rewinding.event}
          purpose={rewinding.purpose}
          onClose={() => {
            setRewinding(null);
          }}
          onRestore={(restore) => rewind(rewinding.event, restore)}
        />
      )}
      {ask}
    </RowsContext>
  );
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
 * The fireflies and "Working... 12s" with the running row's glow (B80); while thinking
 * streams, "Thinking... 4s" previews its latest line and opens to all of it.
 */
function WorkingLine({
  chat,
  thinking,
  thought,
  start,
}: {
  chat: string;
  thinking: boolean;
  thought: string;
  start: string | null;
}) {
  const visible = usePageVisible();
  const now = useSyncExternalStore(visible ? ticks : noTicks, seconds) * 1000;
  const [open, toggle] = useOpen(chat, "live-thinking");
  const streams = thinking && thought !== "";
  const label = `${thinking ? "Thinking..." : "Working..."}${start === null ? "" : ` ${elapsed(now - Date.parse(start))}`}`;
  const last =
    thought
      .split("\n")
      .filter((line) => line.trim() !== "")
      .at(-1) ?? "";
  return (
    <div className="dc-working">
      <button
        className="dc-wline"
        disabled={!streams}
        aria-expanded={streams ? open : undefined}
        onClick={toggle}
      >
        <Fireflies size={10} />
        <span>{label}</span>
        {streams && <Disclosure open={open} />}
      </button>
      {streams &&
        (open ? <p className="dc-thought">{thought}</p> : <p className="dc-live italic">{last}</p>)}
    </div>
  );
}

/** A read-only transcript's rows, as a Claude Code chat or a subagent's work shows them. */
export function ReadOnlyRows({
  chat,
  items,
  terminalPane = null,
  host = null,
}: {
  chat: string;
  items: TranscriptItem[];
  terminalPane?: string | null;
  host?: RowsHost | null;
}) {
  const rows = useMemo<ChatRows>(
    () => ({
      chat,
      session: undefined,
      running: new Set(),
      agentLive: {},
      stopper: null,
      openPixie: () => undefined,
      openTeamWork: null,
      openPixieWork: null,
      openChat: () => undefined,
      messageActions: null,
      terminalPane,
      host,
    }),
    [chat, terminalPane, host],
  );
  return (
    <RowsContext value={rows}>
      {items.map((item) => (
        <div key={item.key} className="dc-item">
          <TranscriptRow item={item} />
        </div>
      ))}
    </RowsContext>
  );
}
