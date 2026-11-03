import { useCallback, useEffect, useRef, useState } from "react";
import type {
  PerfMetric,
  PerfSection,
  PerfSeries,
  PerfTone,
  PerfView,
} from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { barWidths } from "../../../screens/settings/perfText.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Icon } from "../../../ui/Icon.tsx";
import { Button } from "../../ui/controls.tsx";
import { dayShares, perfHeader } from "../parts1/words.ts";
import "../parts1/parts1.css";

/**
 * The Mac's Performance (B115): the last run and its buttons, four cards, the main sections
 * with this run's bars against the previous run's, Advanced (closed each time the page
 * opens) and what changed. The daemon writes every label and number; the Mac app's own
 * sections are measured on the Mac only, so they have no Run here.
 */
export function PerformancePage() {
  const { actions } = useStore();
  const [view, setView] = useState<PerfView | null>(null);
  const [failed, setFailed] = useState(false);
  const [asking, setAsking] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const live = useRef(true);

  const reload = useCallback(
    () =>
      actions.perf().then((found) => {
        if (!live.current) return;
        setFailed(found === null);
        if (found !== null) setView(found);
      }),
    [actions],
  );

  useEffect(() => {
    live.current = true;
    void reload();
    const tick = window.setInterval(() => {
      setNow(new Date());
    }, 60_000);
    return () => {
      live.current = false;
      window.clearInterval(tick);
    };
  }, [reload]);

  // A run started or finished somewhere: read the results again.
  useEffect(
    () =>
      actions.onEvent((event) => {
        if (event.type === "perf.run") void reload();
      }),
    [actions, reload],
  );

  const act = async (call: () => Promise<PerfView | null>) => {
    setAsking(true);
    const found = await call();
    if (!live.current) return;
    setAsking(false);
    if (found === null) void reload();
    else setView(found);
  };

  const running = asking || view?.running != null;
  const ran = view?.running?.sections ?? [];
  const isRunning = (s: PerfSection) =>
    view?.running != null && s.runner === "daemon" && (ran.length === 0 || ran.includes(s.id));
  const neverRun = view !== null && view.last_run === null && view.running === null;
  const section = (s: PerfSection) => (
    <SectionView
      key={s.id}
      section={s}
      running={isRunning(s)}
      canRun={s.runner === "daemon" && !running}
      onRun={() => void act(() => actions.runPerf([s.id]))}
    />
  );
  const main = view?.sections.filter((s) => !s.advanced) ?? [];
  const more = view?.sections.filter((s) => s.advanced) ?? [];

  return (
    <div className="dkp">
      <div className="dkp-head">
        <span aria-live="polite">{perfHeader(view, now)}</span>
        <Button
          disabled={running || (view?.runs ?? 0) === 0}
          onClick={() => void act(() => actions.clearPerf())}
        >
          Clear old runs
        </Button>
        <Button
          kind="primary"
          disabled={running || view === null}
          onClick={() => void act(() => actions.runPerf([]))}
        >
          {running ? "Running" : "Run all"}
        </Button>
      </div>
      {view === null && !failed && (
        <div className="dkp-loading">
          <Fireflies />
        </div>
      )}
      {view !== null && (
        <>
          {neverRun && (
            <p className="dkp-never">
              Nothing measured yet. Run all measures every section on the daemon.
            </p>
          )}
          {view.cards.length > 0 && (
            <div className="dkp-cards">
              {view.cards.map((metric) => (
                <Card key={metric.id} metric={metric} />
              ))}
            </div>
          )}
          {!neverRun && (
            <div className="dkp-legend" aria-hidden="true">
              <span>
                <i className="prev" />
                Previous run
              </span>
              <span>
                <i className="now" />
                This run
              </span>
            </div>
          )}
          {main.map(section)}
          {more.length > 0 && (
            <>
              <button
                type="button"
                className="dkp-fold"
                aria-expanded={advanced}
                onClick={() => {
                  setAdvanced(!advanced);
                }}
              >
                <Icon name="chevr" className={advanced ? "open" : ""} />
                Advanced
              </button>
              {advanced && more.map(section)}
            </>
          )}
          {!neverRun && <Changes changes={view.changes} />}
        </>
      )}
    </div>
  );
}

const TONES: Record<PerfTone, string> = { better: "better", worse: "worse", same: "same" };

function Change({ metric }: { metric: PerfMetric }) {
  if (metric.change === null) return null;
  return <span className={`dkp-change ${TONES[metric.change.tone]}`}>{metric.change.text}</span>;
}

/** One of the four numbers that matter most. */
function Card({ metric }: { metric: PerfMetric }) {
  return (
    <div className="dkp-card">
      <span className="dkp-cardl">{metric.label}</span>
      <div className="dkp-cardv">
        <b>{metric.text}</b>
        <Change metric={metric} />
        {metric.sub !== null && <span className="dkp-sub">{metric.sub}</span>}
      </div>
      {(metric.parts ?? []).slice(0, 4).map((part) => (
        <div key={part.label} className="dkp-part">
          <span>{part.label}</span>
          <span>{part.text}</span>
        </div>
      ))}
    </div>
  );
}

/** A section's title and Run, then its card: the day bars, each metric, or its error. */
function SectionView({
  section,
  running,
  canRun,
  onRun,
}: {
  section: PerfSection;
  running: boolean;
  canRun: boolean;
  onRun: () => void;
}) {
  const ran = section.ran_at !== null;
  return (
    <section className="dkp-sec" aria-label={section.title}>
      <div className="dkp-sech">
        <h2>{section.title}</h2>
        {section.live && (
          <span className="dkp-live" title="A run uses a little of your Claude usage">
            <svg viewBox="0 0 10 12" aria-label="Uses your Claude usage">
              <path d="M6 1 2 7h3l-1 4 4-6H5z" />
            </svg>
          </span>
        )}
        {running ? (
          <Fireflies size={9} label="Running" />
        ) : (
          section.runner === "daemon" && (
            <Button
              kind="plain"
              aria-label={`Run ${section.title}`}
              disabled={!canRun}
              onClick={onRun}
            >
              <Icon name="play" />
              Run
            </Button>
          )
        )}
      </div>
      <div className="dkp-box">
        {section.series !== null && ran && <DayBars series={section.series} />}
        {section.error !== null ? (
          <p className="dkp-error">{section.error}</p>
        ) : (
          !ran && !running && <p className="dkp-empty">Not run yet</p>
        )}
        {section.metrics.length > 0 &&
          ran &&
          (section.series !== null ? (
            <PlainRows metrics={section.metrics} />
          ) : (
            <CompareRows metrics={section.metrics} />
          ))}
      </div>
      {section.note !== null && <p className="dkp-note">{section.note}</p>}
    </section>
  );
}

/** Label with its quiet word, the previous and this run's bars, the value and the change. */
function CompareRows({ metrics }: { metrics: PerfMetric[] }) {
  const widths = barWidths(metrics);
  return (
    <div className="dkp-compare">
      {metrics.map((metric) => {
        const bar = widths.get(metric.id);
        return (
          <div key={metric.id} className="dkp-crow">
            <span className="dkp-clab">
              {metric.label}
              {metric.sub !== null && <span className="dkp-sub">{metric.sub}</span>}
            </span>
            <span className="dkp-bars" aria-hidden="true">
              <i className="prev" style={{ width: `${String(bar?.previous ?? 0)}%` }} />
              <i className="now" style={{ width: `${String(bar?.value ?? 0)}%` }} />
            </span>
            <span
              className="dkp-val"
              title={
                metric.previous_text === null ? metric.text : `Previous run ${metric.previous_text}`
              }
            >
              {metric.text}
            </span>
            <span className="dkp-cc">
              <Change metric={metric} />
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** Rows without bars, under a section's day bars. */
function PlainRows({ metrics }: { metrics: PerfMetric[] }) {
  return (
    <div className="dkp-plain">
      {metrics.map((metric) => (
        <div key={metric.id}>
          <span>{metric.label}</span>
          <span className="dkp-val">{metric.text}</span>
          <Change metric={metric} />
        </div>
      ))}
    </div>
  );
}

/** A day series as bars, tallest day full height, with each day's value on hover. */
function DayBars({ series }: { series: PerfSeries }) {
  const shares = dayShares(series.points.map((p) => p.value));
  return (
    <div className="dkp-days" role="img" aria-label={series.label}>
      {series.points.map((point, index) => (
        <i
          key={point.day}
          title={`${point.day}: ${String(Math.round(point.value))}`}
          style={{ height: Math.max(2, 48 * (shares[index] ?? 0)) }}
        />
      ))}
    </div>
  );
}

/** What changed since the previous run, worst first, as the daemon tells it. */
function Changes({ changes }: { changes: PerfView["changes"] }) {
  return (
    <section className="dkp-sec" aria-label="What changed">
      <div className="dkp-sech">
        <h2>What changed</h2>
      </div>
      <div className="dkp-box">
        {changes.length === 0 && (
          <p className="dkp-empty ui">Nothing changed much since the previous run</p>
        )}
        {changes.map((change) => (
          <div key={change.text} className="dkp-changed">
            <i className={TONES[change.tone]} />
            <span>{change.text}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
