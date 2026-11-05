// What sits just above a chat's composer on the Mac: the running tasks (BackgroundBar), the
// review that waits (PendingReviewBar), the usage limit pause (LimitPauseBar), Autopilot's
// run, and the messages sent while the agent works (PendingMessages).
import { useEffect, useState } from "react";
import { reviewOf } from "../../api/payloads.ts";
import type {
  Approval,
  AutopilotRun,
  BackgroundSummary,
  LimitPause,
  QueuedMessage,
  Session,
} from "../../api/types.ts";
import { useReview } from "../../screens/approvals/hooks.ts";
import { runLine, stepLine } from "../../screens/chat/useAutopilot.ts";
import { countdown, resetLabel } from "../../format.ts";
import { asDraftFiles } from "../../store/actions.ts";
import { useStore } from "../../store/context.ts";
import { engineName, pendingFor } from "../../store/selectors.ts";
import { bashBlocks } from "../../transcript/build.ts";
import { elapsed } from "../../transcript/activity.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { fromQueued } from "../../ui/sentFile.ts";
import { Button } from "../ui/controls.tsx";
import { DiffCounts } from "./bits.tsx";
import { useOpen } from "./expanded.ts";
import { Glyph } from "./glyphs.tsx";
import { Sent } from "./ImageSheet.tsx";
import { PublishSheet } from "./PublishSheet.tsx";
import { DiffSheet } from "./ReviewSheets.tsx";
import { StopTaskButton } from "./Rows.tsx";
import { usePrefill } from "./usePrefill.tsx";

const IN_FLIGHT = new Set<Session["state"]>(["starting", "running", "waiting"]);
const NO_QUEUE: QueuedMessage[] = [];

/** The clock, read again every second while shown. */
function useNow(): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);
  return now;
}

/**
 * "N running tasks" while any of the chat's subagents or background commands runs (B76);
 * a click opens the list upwards, each with how long it has run and Stop.
 */
export function BackgroundBar({ chat, summary }: { chat: string; summary: BackgroundSummary }) {
  const [open, toggle] = useOpen(chat, "background-bar");
  const running = summary.items.filter((item) => item.status === "running");
  if (running.length === 0) return null;
  const label = running.length === 1 ? "1 running task" : `${String(running.length)} running tasks`;
  return (
    <div className="dc-bar dc-bg">
      {open && <RunningList items={running} />}
      <button
        className="dc-bgsum"
        aria-expanded={open}
        title={open ? "Hide running tasks" : "Show running tasks"}
        onClick={toggle}
      >
        <Fireflies size={9} />
        <span className="dc-shimmer">{label}</span>
        <span className="grow" />
        <Glyph name={open ? "chevron" : "chevronUp"} size={9} className="dc-t3" />
      </button>
    </div>
  );
}

function RunningList({ items }: { items: BackgroundSummary["items"] }) {
  const now = useNow();
  return (
    <div className="dc-bglist">
      <span className="dc-label">Running</span>
      <ul aria-label="Running">
        {items.map((item) => (
          <li
            key={item.id}
            title={item.description === null ? item.name : `${item.name}: ${item.description}`}
          >
            <Fireflies size={9} />
            <Glyph name={item.kind === "bash" ? "terminal" : "agent"} size={10} className="dc-t3" />
            <b>{item.name}</b>
            <span className="dc-bgdesc">{item.description ?? ""}</span>
            <span className="dc-bgtime">
              {item.started_at === null ? "" : elapsed(now - Date.parse(item.started_at))}
            </span>
            <StopTaskButton id={item.id} name={item.name} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** One quiet line while the chat's review waits (B56): the files and Review. */
export function ReviewBar({ session }: { session: Session }) {
  const { state } = useStore();
  const pending = pendingFor(state, session.id).find((a) => a.kind === "review");
  if (pending === undefined) return null;
  return <PendingReview key={pending.id} approval={pending} session={session} />;
}

function PendingReview({ approval, session }: { approval: Approval; session: Session }) {
  const review = useReview(approval, session);
  const [sheet, setSheet] = useState<"diff" | "publish" | "commit" | null>(null);
  const { files, additions, deletions } = reviewOf(approval);
  const close = () => {
    setSheet(null);
  };
  return (
    <div
      className="dc-bar dc-line-bar"
      role="group"
      aria-label={`${String(files)} files changed, ${String(additions)} added, ${String(deletions)} removed`}
    >
      <Glyph name="diff" size={11} className="dc-ok" />
      <span className="dc-barl">
        {files === 1 ? "1 file changed" : `${String(files)} files changed`}
      </span>
      <DiffCounts added={additions} removed={deletions} />
      <span className="grow" />
      <Button
        title="See the changes and approve them"
        onClick={() => {
          setSheet("diff");
        }}
      >
        Review
      </Button>
      {sheet === "diff" && (
        <DiffSheet
          review={review}
          onClose={close}
          onApprove={(commitOnly) => {
            setSheet(commitOnly ? "commit" : "publish");
          }}
        />
      )}
      {(sheet === "publish" || sheet === "commit") && (
        <PublishSheet
          approval={approval}
          session={session}
          review={review}
          commitOnly={sheet === "commit"}
          onClose={close}
        />
      )}
    </div>
  );
}

const WINDOWS: Readonly<Record<string, string>> = {
  five_hour: "5-hour usage",
  seven_day: "weekly",
  seven_day_opus: "weekly Opus",
  seven_day_sonnet: "weekly Sonnet",
  overage: "extra usage",
};

/** While the chat is paused at a usage limit (B78): which, when it goes on, Resume now. */
export function LimitBar({ session }: { session: Session }) {
  if (session.limit_pause === null) return null;
  return <Limit key={session.limit_pause.since} id={session.id} pause={session.limit_pause} />;
}

function Limit({ id, pause }: { id: string; pause: LimitPause }) {
  const { state, actions } = useStore();
  const [busy, setBusy] = useState(false);
  const now = useNow();
  const waiting = (state.queued[id] ?? NO_QUEUE).filter((m) => !m.sent).length;
  const words = (pause.window === null ? undefined : WINDOWS[pause.window]) ?? "usage";
  const goes = pause.resets_at === null ? "tries again" : "goes on";
  const plan =
    waiting === 0
      ? "Then it continues where it left off."
      : waiting === 1
        ? "Your queued message sends then."
        : `Your ${String(waiting)} queued messages send then.`;
  return (
    <div className="dc-bar dc-limit" role="group" aria-label={`Paused at the ${words} limit`}>
      <Glyph name="pause" size={12} className="dc-int" />
      <div className="dc-limitt">
        <b>{`Paused at the ${words} limit`}</b>
        <span>
          {resetLabel(pause.resets_at, new Date(now))} · {goes}{" "}
          {countdown(Date.parse(pause.resume_at) - now)}
        </span>
        <span>{plan}</span>
      </div>
      <Button
        disabled={busy}
        title="Go on now instead of waiting for the reset"
        onClick={() => {
          setBusy(true);
          void actions.resumeLimit(id).then(() => {
            setBusy(false);
          });
        }}
      >
        Resume now
      </Button>
    </div>
  );
}

/** While the chat runs on Autopilot (B120): its step, how long, its decisions, Turn off. */
export function AutopilotBar({ session }: { session: Session }) {
  if (session.autopilot == null) return null;
  return <Run key={session.autopilot.started_at} id={session.id} run={session.autopilot} />;
}

function Run({ id, run }: { id: string; run: AutopilotRun }) {
  const { state, actions } = useStore();
  const [busy, setBusy] = useState(false);
  const now = useNow();
  const step = stepLine(state.tracking[id]?.tasks ?? []);
  return (
    <div className="dc-bar dc-line-bar" role="group" aria-label="Autopilot">
      <Glyph name="infinity" size={13} className="dc-bad" />
      <span className="dc-barl">Autopilot</span>
      {step !== null && (
        <span className="dc-apstep" title={step}>
          {step}
        </span>
      )}
      <span className="dc-bgtime">{runLine(run, now)}</span>
      <span className="grow" />
      <Button
        disabled={busy}
        onClick={() => {
          setBusy(true);
          void actions.setAutopilot(id, { on: false }).then(() => {
            setBusy(false);
          });
        }}
      >
        Turn off
      </Button>
    </div>
  );
}

/**
 * Messages sent while the agent works that it has not read yet (B59), oldest first, each
 * with Edit, Send now and Remove. Once read it shows in the transcript where it was read.
 */
export function PendingMessages({ session, draftKey }: { session: Session; draftKey: string }) {
  const { state, actions } = useStore();
  const messages = state.queued[session.id] ?? NO_QUEUE;
  const [sending, setSending] = useState<{ list: QueuedMessage[]; ids: string[] }>({
    list: messages,
    ids: [],
  });
  const tapped = sending.list === messages ? sending.ids : [];
  const { fill, ask } = usePrefill(draftKey);
  const working = IN_FLIGHT.has(session.state);
  const agent = engineName(state, session.provider);
  const sendNow = async (id: string) => {
    setSending({ list: messages, ids: [...tapped, id] });
    if (!(await actions.sendNow(session.id, id))) {
      setSending((s) => ({ ...s, ids: s.ids.filter((x) => x !== id) }));
    }
  };
  const edit = async (message: QueuedMessage) => {
    if ((await actions.cancelQueued(session.id, message.id)) !== "removed") return;
    fill({ text: bashBlocks(message.text).rest, files: asDraftFiles(message.attachments) });
  };
  return (
    <>
      {messages.length > 0 && (
        <ul className="dc-pending" aria-label="Pending messages">
          {messages.map((message) => {
            const { commands, rest } = bashBlocks(message.text);
            return (
              <li key={message.id} className="dc-pend" aria-label={`Pending: ${rest}`}>
                <div className="dc-pendt">
                  {commands.length > 0 && (
                    <span className="dc-pendc">
                      {commands.map((c) => `! ${c.command}`).join("  ")}
                    </span>
                  )}
                  <span className="dc-pendm">{rest}</span>
                  {message.attachments.length > 0 && (
                    <Sent files={message.attachments.map(fromQueued)} />
                  )}
                  <span className="dc-pendn">
                    {message.sent
                      ? `${agent} reads this at its next step`
                      : working
                        ? "Sends when this turn ends"
                        : "Waiting"}
                  </span>
                </div>
                <span className="dc-penda">
                  <button
                    className="dk-btn k-plain icon"
                    title="Edit: take the message back into the composer"
                    aria-label="Edit pending message"
                    onClick={() => void edit(message)}
                  >
                    <Glyph name="edit" size={10} />
                  </button>
                  <Button
                    disabled={tapped.includes(message.id)}
                    title="Stop the turn and send this message now"
                    onClick={() => void sendNow(message.id)}
                  >
                    Send now
                  </Button>
                  <button
                    className="dk-btn k-plain icon"
                    title="Remove this message"
                    aria-label="Remove pending message"
                    onClick={() => void actions.cancelQueued(session.id, message.id)}
                  >
                    <Glyph name="close" size={9} />
                  </button>
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {ask}
    </>
  );
}
