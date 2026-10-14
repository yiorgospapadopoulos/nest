import { useState } from "react";
import type { PixieReport } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import type { SuggestedHabit } from "../../transcript/build.ts";
import { SEVERITIES, scheduleText, triggersText } from "../pixies/habits.ts";

/** Only web addresses open from a card; anything else a pixie wrote stays text. */
function safeLink(link: string | null): string | null {
  return link !== null && /^https?:\/\//i.test(link) ? link : null;
}

/** The habit a report came from, as a line: its name once the pixie's habits are known. */
function useHabitLine(report: PixieReport): string | null {
  const { state } = useStore();
  if (report.habit_id === null) return null;
  const habit = state.habits[report.pixie_id]?.find((h) => h.id === report.habit_id);
  return habit === undefined ? "From a habit" : `From habit ${habit.name}`;
}

/** A report a pixie posted (B42): its severity, title, body, link and habit. */
export function ReportCard({ reportId, ev }: { reportId: string; ev: string }) {
  const { state } = useStore();
  const report = state.reports[reportId];
  if (report === undefined) {
    return (
      <div className="pxcard" role="group" aria-label="Report" data-ev={ev}>
        <div className="pxcb">
          <span className="pxcm">This report is no longer kept.</span>
        </div>
      </div>
    );
  }
  return <KnownReport report={report} ev={ev} />;
}

function KnownReport({ report, ev }: { report: PixieReport; ev: string }) {
  const from = useHabitLine(report);
  const link = safeLink(report.link);
  return (
    <div
      className={`pxcard pxrep sev-${report.severity}`}
      role="group"
      aria-label={`Report: ${report.title}`}
      data-ev={ev}
    >
      <div className="pxcb">
        <span className="pxsev">{SEVERITIES[report.severity]}</span>
        <b>{report.title}</b>
        {report.body !== "" && <span className="pxrb">{report.body}</span>}
        {from !== null && <span className="pxcm">{from}</span>}
      </div>
      {link !== null && (
        <div className="pxca">
          <a className="b qb2" href={link} target="_blank" rel="noreferrer">
            Open link
          </a>
        </div>
      )}
    </div>
  );
}

interface ChoicesProps {
  options: string[];
  // The user wrote after the card.
  answered: boolean;
  pixieId: string;
  ev: string;
}

/** Reply buttons (B42): a tap sends the option as the user's message, once. */
export function ChoicesCard({ options, answered, pixieId, ev }: ChoicesProps) {
  const { actions } = useStore();
  // While a reply is being sent, and once one was.
  const [busy, setBusy] = useState(false);
  const choose = async (option: string) => {
    setBusy(true);
    const sent = await actions.sendToPixie(pixieId, option);
    if (sent === null) setBusy(false);
  };
  return (
    <div className="pxcard pxchoices" role="group" aria-label="Choices" data-ev={ev}>
      <div className="pxca">
        {options.map((option) => (
          <button
            key={option}
            className="b qb2"
            disabled={answered || busy}
            onClick={() => void choose(option)}
          >
            {option}
          </button>
        ))}
      </div>
    </div>
  );
}

interface SuggestionProps {
  habit: SuggestedHabit;
  pixieId: string;
  ev: string;
}

/**
 * A habit the pixie suggests (B42): its schedule, triggers and prompt (folded). Start
 * creates it, enabled; nothing runs before. A habit of that name already started.
 */
export function SuggestionCard({ habit, pixieId, ev }: SuggestionProps) {
  const { state, actions } = useStore();
  const [busy, setBusy] = useState(false);
  const [started, setStarted] = useState(false);
  const known = started || (state.habits[pixieId] ?? []).some((h) => h.name === habit.name);
  const triggers = triggersText(habit.triggers);
  const start = async () => {
    setBusy(true);
    const created = await actions.createHabit(pixieId, { ...habit, enabled: true });
    setBusy(false);
    if (created !== null) setStarted(true);
  };
  return (
    <div
      className="pxcard pxsug"
      role="group"
      aria-label={`Suggested habit: ${habit.name}`}
      data-ev={ev}
    >
      <div className="pxcb">
        <span className="pxsev">Suggested habit</span>
        <b>{habit.name}</b>
        <span className="pxcm">{scheduleText(habit.schedule)}</span>
        {triggers !== "" && <span className="pxcm">{triggers}</span>}
        <details className="pxsugp">
          <summary>Prompt</summary>
          <span className="pxrb">{habit.prompt}</span>
        </details>
      </div>
      <div className="pxca">
        {known ? (
          <span className="pxdone">Started</span>
        ) : (
          <button className="b b-pri" disabled={busy} onClick={() => void start()}>
            Start
          </button>
        )}
      </div>
    </div>
  );
}
