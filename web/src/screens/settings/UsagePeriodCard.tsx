import { useState, type PointerEvent } from "react";
import type { PeriodUnit, UsagePeriod } from "../../api/types.ts";
import { tokens } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { LinkRow, Row, Section } from "./rows.tsx";
import {
  UNITS,
  barHeight,
  barTip,
  chatCount,
  isoDay,
  periodRange,
  periodTitle,
  stepDate,
  ticks,
} from "./usageText.ts";
import { useUsage } from "./useUsage.ts";

/** The tokens Nest counted: a day, week, month or year at a time, as bars and totals (B84). */
export function UsagePeriodCard({ onDetails }: { onDetails: () => void }) {
  const { actions } = useStore();
  const today = new Date();
  const { unit, date, period } = useUsage(today);
  // Until the Mac answers, this phone's calendar says whether the period is the current one.
  const current = period?.current ?? periodRange(unit, date).end >= isoDay(today);
  const amount = (n: number | undefined) => (n === undefined ? "-" : tokens(n));

  return (
    <Section className="useq">
      <div className="pad uper">
        <div className="mseg useg" role="group" aria-label="Period">
          {UNITS.map((u) => (
            <button
              key={u.value}
              aria-pressed={u.value === unit}
              onClick={() => {
                actions.viewUsage(u.value, null);
              }}
            >
              {u.label}
            </button>
          ))}
        </div>
        <div className="unav">
          <button
            className="ib"
            aria-label="Previous period"
            onClick={() => {
              actions.viewUsage(unit, stepDate(unit, date, -1));
            }}
          >
            <Icon name="chevl" />
          </button>
          <b aria-live="polite">{periodTitle(unit, date, today)}</b>
          <button
            className="ib"
            aria-label="Next period"
            disabled={current}
            onClick={() => {
              actions.viewUsage(unit, stepDate(unit, date, 1));
            }}
          >
            <Icon name="chevr" />
          </button>
        </div>
        <Bars key={`${unit} ${date}`} unit={unit} date={date} period={period} now={today} />
      </div>
      <Row label="Chats">
        <span className="sval num">
          {amount(period === null ? undefined : period.tokens.total - period.subagents.total)}
        </span>
      </Row>
      <Row label="Subagents">
        <span className="sval num">{amount(period?.subagents.total)}</span>
      </Row>
      <Row label={period === null ? "Total" : `Total · ${chatCount(period.sessions)}`}>
        <span className="sval num utot">{amount(period?.tokens.total)}</span>
      </Row>
      <LinkRow icon={null} label="Details" onOpen={onDetails} />
    </Section>
  );
}

interface BarsProps {
  unit: PeriodUnit;
  date: string;
  period: UsagePeriod | null;
  now: Date;
}

/** The period's bars; touching one (or sliding across) shows its numbers under them. */
function Bars({ unit, date, period, now }: BarsProps) {
  const [picked, setPicked] = useState<number | null>(null);
  const bars = period?.bars ?? [];
  const peak = Math.max(0, ...bars.map((b) => b.tokens));
  const chosen = picked === null ? undefined : bars[picked];

  const pick = (event: PointerEvent<HTMLDivElement>, toggle: boolean) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (bars.length === 0 || box.width <= 0) return;
    const at = Math.floor(((event.clientX - box.left) / box.width) * bars.length);
    const index = Math.min(bars.length - 1, Math.max(0, at));
    setPicked(toggle && index === picked ? null : index);
  };

  return (
    <>
      <div
        className="ubars"
        role="group"
        aria-label="Tokens over the period"
        onPointerDown={(event) => {
          pick(event, true);
        }}
        onPointerMove={(event) => {
          if (event.buttons !== 0) pick(event, false);
        }}
      >
        {bars.map((bar, i) => {
          const tip = barTip(unit, bar);
          const future = new Date(bar.start).getTime() > now.getTime();
          const kind = future ? "fut" : bar.tokens > 0 ? "on" : "";
          return (
            <span
              key={bar.start}
              className={["ubar", kind, i === picked ? "sel" : ""].filter(Boolean).join(" ")}
              role="img"
              aria-label={tip}
              title={tip}
              style={{ height: `${String(barHeight(bar.tokens, peak))}px` }}
            />
          );
        })}
      </div>
      <div className="uticks" aria-live="polite">
        {chosen === undefined ? (
          ticks(unit, date).map((t) => <span key={t}>{t}</span>)
        ) : (
          <span className="utip">{barTip(unit, chosen)}</span>
        )}
      </div>
    </>
  );
}
