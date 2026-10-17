import { useEffect, useState, type CSSProperties } from "react";
import type { DayUsage, MonthUsage } from "../../api/types.ts";
import { monthName, tokens } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";

// How far back the calendar goes, in months before the current one.
const HISTORY = 11;
const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

/** Monthly totals and a daily token calendar, a month at a time. */
export function UsageCalendar({ today = new Date() }: { today?: Date }) {
  const { actions } = useStore();
  const [back, setBack] = useState(0);
  const [usage, setUsage] = useState<MonthUsage | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const shown = new Date(today.getFullYear(), today.getMonth() - back, 1);
  const year = shown.getFullYear();
  const month = shown.getMonth() + 1;

  useEffect(() => {
    let live = true;
    void actions.month(year, month).then((loaded) => {
      if (live) setUsage(loaded);
    });
    return () => {
      live = false;
    };
  }, [actions, year, month]);

  const move = (step: number) => {
    setBack((current) => Math.min(HISTORY, Math.max(0, current - step)));
    setUsage(null);
    setSelected(null);
  };
  const current = usage !== null && usage.year === year && usage.month === month ? usage : null;
  const days = current === null ? [] : current.days;
  const max = Math.max(1, ...days.map((d) => d.tokens));
  const offset = (shown.getDay() + 6) % 7;
  const chosen = days.find((d) => d.date === selected);

  return (
    <>
      <div className="ulbl">
        {back === 0 ? "This month" : `${monthName(month)} ${String(year)}`}
      </div>
      <div className="utot">
        <div>
          <b>{current === null ? "-" : current.sessions}</b>
          <small>Sessions</small>
        </div>
        <div>
          <b>{current === null ? "-" : tokens(current.tokens.total)}</b>
          <small>Total tokens</small>
        </div>
      </div>
      <div className="cal">
        <div className="cal-h">
          <button
            className="ib"
            aria-label="Previous month"
            disabled={back >= HISTORY}
            onClick={() => {
              move(-1);
            }}
          >
            <Icon name="chevl" />
          </button>
          <b aria-live="polite">
            {monthName(month)} {year}
          </b>
          <button
            className="ib"
            aria-label="Next month"
            disabled={back === 0}
            onClick={() => {
              move(1);
            }}
          >
            <Icon name="chevr" />
          </button>
        </div>
        <div className="cal-g">
          {WEEKDAYS.map((w) => (
            <span key={w} className="cal-w" aria-hidden="true">
              {w}
            </span>
          ))}
          {Array.from({ length: offset }, (_, i) => (
            <span key={`pad-${String(i)}`} />
          ))}
          {days.map((day) => (
            <Day
              key={day.date}
              day={day}
              max={max}
              future={back === 0 && Number(day.date.slice(8)) > today.getDate()}
              today={back === 0 && Number(day.date.slice(8)) === today.getDate()}
              selected={selected === day.date}
              onSelect={() => {
                setSelected(selected === day.date ? null : day.date);
              }}
            />
          ))}
        </div>
        <div className="cdet" aria-live="polite">
          {chosen === undefined ? (
            "Tap a day for its tokens and sessions."
          ) : (
            <>
              <b>{dayName(chosen.date)}</b> {describe(chosen)}
            </>
          )}
        </div>
      </div>
    </>
  );
}

function dayName(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function describe(day: DayUsage): string {
  if (day.tokens === 0) return "No sessions";
  const sessions = `${String(day.sessions)} session${day.sessions === 1 ? "" : "s"}`;
  return `${day.tokens.toLocaleString("en-US")} tokens, ${sessions}`;
}

interface DayProps {
  day: DayUsage;
  max: number;
  future: boolean;
  today: boolean;
  selected: boolean;
  onSelect: () => void;
}

function Day({ day, max, future, today, selected, onSelect }: DayProps) {
  const number = Number(day.date.slice(8));
  if (future) {
    return (
      <span className="cd fut">
        <span className="n">{number}</span>
      </span>
    );
  }
  const heat = day.tokens > 0 ? 0.08 + 0.6 * (day.tokens / max) : 0;
  const classes = ["cd", heat > 0.45 ? "hi" : "", today ? "today" : ""].filter(Boolean).join(" ");
  return (
    <button
      className={classes}
      style={{ "--h": heat.toFixed(2) } as CSSProperties}
      aria-pressed={selected}
      aria-label={`${dayName(day.date)}: ${describe(day)}`}
      onClick={onSelect}
    >
      <span className="n">{number}</span>
      <span className="v">{day.tokens > 0 ? tokens(day.tokens) : ""}</span>
    </button>
  );
}
