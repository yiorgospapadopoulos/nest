// The cards a pixie posts in its own chat (B41, B42), as the Mac's PixieCards.swift: a
// chat it started, that chat's pull request, a report, reply choices, a suggested habit.
import { useState } from "react";
import type { PixieReport, Session } from "../../api/types.ts";
import { SEVERITIES, scheduleText, triggersText } from "../../screens/pixies/habits.ts";
import { prView } from "../../screens/chat/prView.ts";
import { useStore } from "../../store/context.ts";
import { chatStatus, pendingFor } from "../../store/selectors.ts";
import type { CardItem, SuggestedHabit } from "../../transcript/build.ts";
import { Dot } from "../../ui/bits.tsx";
import { Button } from "../ui/controls.tsx";
import { Disclosure, Glyph } from "./glyphs.tsx";
import { useRows } from "./rowsContext.ts";

const REVIEWS: Record<string, string> = {
  APPROVED: "approved",
  CHANGES_REQUESTED: "changes requested",
  REVIEW_REQUIRED: "review required",
};

/** A card in a pixie's chat; nothing in a project chat, which holds none. */
export function PixieCard({ item, ev }: { item: CardItem; ev: string }) {
  const { session } = useRows();
  const pixie = session?.pixie_id ?? null;
  if (pixie === null) return null;
  switch (item.card) {
    case "report":
      return <ReportCard reportId={item.reportId} ev={ev} />;
    case "choices":
      return <ChoicesCard options={item.options} answered={item.answered} pixie={pixie} ev={ev} />;
    case "habit_suggestion":
      return <SuggestionCard habit={item.habit} pixie={pixie} ev={ev} />;
    default:
      return <ChatCard card={item.card} sessionId={item.sessionId} ev={ev} />;
  }
}

/** A chat the pixie started with its live state, or its pull request, and Open. */
function ChatCard({
  card,
  sessionId,
  ev,
}: {
  card: "session" | "pr";
  sessionId: string;
  ev: string;
}) {
  const { state } = useStore();
  const { openChat } = useRows();
  const session = state.sessions[sessionId];
  if (session === undefined)
    return (
      <p className="dc-sys" data-ev={ev}>
        A chat that is no longer here
      </p>
    );
  return (
    <div
      className="dc-card"
      role="group"
      aria-label={`${card === "pr" ? "Pull request" : "Chat"}: ${session.title}`}
      data-ev={ev}
    >
      <div className="dc-cardb">
        {card === "session" ? <SessionBody session={session} /> : <PrBody session={session} />}
      </div>
      {card === "pr" && session.pr_url !== null && (
        <a
          className="dk-btn k-plain icon"
          href={session.pr?.url ?? session.pr_url}
          target="_blank"
          rel="noreferrer"
          title="Open on GitHub"
          aria-label="Open on GitHub"
        >
          <Glyph name="open" size={11} />
        </a>
      )}
      <Button
        title={`Open ${session.title}`}
        onClick={() => {
          openChat(session.id);
        }}
      >
        Open
      </Button>
    </div>
  );
}

function SessionBody({ session }: { session: Session }) {
  const { state } = useStore();
  const status = chatStatus(session, pendingFor(state, session.id));
  return (
    <>
      <span className="dc-cardt">{session.title}</span>
      <span className="dc-cardm">
        {session.repo}
        <span className="dc-status">
          <Dot tone={status.tone} />
          {status.label}
        </span>
      </span>
    </>
  );
}

function PrBody({ session }: { session: Session }) {
  if (session.pr_url === null) {
    return (
      <>
        <span className="dc-cardt">{session.title}</span>
        <span className="dc-cardm">No pull request yet</span>
      </>
    );
  }
  const view = prView(session.pr, session.pr_url);
  const decision = session.pr?.review_decision ?? null;
  return (
    <>
      <span className="dc-cardt">
        <Glyph name="pr" size={10} />
        {view.label} {session.pr?.title ?? session.title}
      </span>
      <span className="dc-cardm">
        <Dot tone={view.tone} />
        {view.text}
        {decision !== null && `, ${REVIEWS[decision] ?? decision.toLowerCase()}`}
      </span>
    </>
  );
}

function ReportCard({ reportId, ev }: { reportId: string; ev: string }) {
  const { state } = useStore();
  const report = state.reports[reportId];
  if (report === undefined)
    return (
      <p className="dc-sys" data-ev={ev}>
        This report is no longer kept.
      </p>
    );
  return <KnownReport report={report} ev={ev} />;
}

/** A report: its severity mark, title, body, link and the habit it came from. */
function KnownReport({ report, ev }: { report: PixieReport; ev: string }) {
  const { state } = useStore();
  const habit =
    report.habit_id === null
      ? null
      : (state.habits[report.pixie_id]?.find((h) => h.id === report.habit_id)?.name ?? "");
  const link = report.link !== null && /^https?:\/\//i.test(report.link) ? report.link : null;
  return (
    <div
      className={`dc-card col dc-rep sev-${report.severity}`}
      role="group"
      aria-label={`Report: ${report.title}`}
      data-ev={ev}
    >
      <span className="dc-rephead">
        <span className="dc-sev">{SEVERITIES[report.severity]}</span>
        {habit !== null && (
          <span className="dc-cardm">{habit === "" ? "From a habit" : `From habit ${habit}`}</span>
        )}
      </span>
      <span className="dc-cardt strong">{report.title}</span>
      {report.body !== "" && <span className="dc-cardbody">{report.body}</span>}
      {link !== null && (
        <a
          className="dc-replink"
          href={link}
          target="_blank"
          rel="noreferrer"
          title={`Open ${link}`}
        >
          <Glyph name="open" size={10} />
          <span>{link}</span>
        </a>
      )}
    </div>
  );
}

/** Up to four replies; a click sends one as the user's message, and the buttons are spent. */
function ChoicesCard({
  options,
  answered,
  pixie,
  ev,
}: {
  options: string[];
  answered: boolean;
  pixie: string;
  ev: string;
}) {
  const { actions } = useStore();
  const [sent, setSent] = useState<string | null>(null);
  const spent = answered || sent !== null;
  return (
    <div className="dc-choices" role="group" aria-label="Reply choices" data-ev={ev}>
      {options.map((option) => (
        <Button
          key={option}
          kind={sent === option ? "primary" : "soft"}
          disabled={spent}
          title={spent ? "Already answered" : `Reply "${option}"`}
          onClick={() => {
            setSent(option);
            void actions.sendToPixie(pixie, option).then((done) => {
              if (done === null) setSent(null);
            });
          }}
        >
          {option}
        </Button>
      ))}
    </div>
  );
}

/** A habit the pixie proposes, its instructions folded, and Start; "Started" once it exists. */
function SuggestionCard({
  habit,
  pixie,
  ev,
}: {
  habit: SuggestedHabit;
  pixie: string;
  ev: string;
}) {
  const { state, actions } = useStore();
  const [shown, setShown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [started, setStarted] = useState(false);
  const known = started || (state.habits[pixie] ?? []).some((h) => h.name === habit.name);
  const triggers = triggersText(habit.triggers);
  const summary = [scheduleText(habit.schedule), triggers]
    .filter((part) => part !== "")
    .join(" · ");
  return (
    <div
      className="dc-card col"
      role="group"
      aria-label={`Suggested habit: ${habit.name}`}
      data-ev={ev}
    >
      <span className="dc-rephead quiet">
        <Glyph name="repeat" size={10} />
        Suggested habit
      </span>
      <span className="dc-cardt strong">{habit.name}</span>
      {summary !== "" && <span className="dc-cardm">{summary}</span>}
      <button
        className="dc-line quiet small"
        aria-expanded={shown}
        onClick={() => {
          setShown(!shown);
        }}
      >
        <Disclosure open={shown} />
        <span>{shown ? "Hide instructions" : "Show instructions"}</span>
      </button>
      {shown && <span className="dc-cardbody">{habit.prompt}</span>}
      <span className="dc-cardact">
        {known ? (
          <span className="dc-status ok">
            <Dot tone="rev" />
            Started
          </span>
        ) : (
          <Button
            kind="primary"
            disabled={busy}
            title="Create this habit and turn it on"
            onClick={() => {
              setBusy(true);
              void actions.createHabit(pixie, { ...habit, enabled: true }).then((created) => {
                setBusy(false);
                if (created !== null) setStarted(true);
              });
            }}
          >
            <Glyph name="play" size={9} />
            Start
          </Button>
        )}
      </span>
    </div>
  );
}
