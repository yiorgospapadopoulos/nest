import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { PerfMetric, PerfSection, PerfSeries, PerfTone, PerfView } from "../../api/types.ts";
import { activityTime } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { barWidths, durationText } from "./perfText.ts";
import { Loading, Section } from "./rows.tsx";

const TONE: Record<PerfTone, string> = { better: "pf-better", worse: "pf-worse", same: "pf-same" };

// A card with more parts than this shows them as one stacked bar, else as lines.
const PART_LINES = 2;

/**
 * Settings > Performance (B115): the latest run of each section against the one before it,
 * as the daemon measured and worded them. Runs start here; a `perf.run` event, from here
 * or the Mac, reloads the page.
 */
export function PerformancePage() {
  const { actions } = useStore();
  const [view, setView] = useState<PerfView | null>(null);
  const [failed, setFailed] = useState(false);
  // A run or clear asked for and not answered yet.
  const [asking, setAsking] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const live = useRef(true);

  const reload = useCallback(
    () =>
      actions.perf().then((found) => {
        if (!live.current) return;
        if (found === null) setFailed(true);
        else setView(found);
      }),
    [actions],
  );

  useEffect(() => {
    live.current = true;
    void reload();
    return () => {
      live.current = false;
    };
  }, [reload]);

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
    // Refused, such as a run already under way elsewhere: show what is true now.
    if (found === null) void reload();
    else setView(found);
  };

  if (view === null) {
    return failed ? (
      <Section>
        <div className="srow note">Could not load</div>
      </Section>
    ) : (
      <Loading />
    );
  }

  const busy = asking || view.running !== null;
  const ran = view.running?.sections ?? [];
  const isRunning = (s: PerfSection) =>
    view.running !== null && s.runner === "daemon" && (ran.length === 0 || ran.includes(s.id));
  const run = (sections: string[]) => void act(() => actions.runPerf(sections));
  const main = view.sections.filter((s) => !s.advanced);
  const more = view.sections.filter((s) => s.advanced);
  const card = (s: PerfSection) => (
    <SectionCard
      key={s.id}
      section={s}
      running={isRunning(s)}
      disabled={busy}
      onRun={() => {
        run([s.id]);
      }}
    />
  );

  return (
    <div className="pf">
      <div className="pf-head">
        <span className="pf-meta" aria-live="polite">
          <RunState view={view} />
        </span>
        <div className="pf-btns">
          <button
            className="b"
            disabled={busy || view.runs === 0}
            onClick={() => void act(() => actions.clearPerf())}
          >
            Clear old runs
          </button>
          <button
            className="b b-pri"
            disabled={busy}
            onClick={() => {
              run([]);
            }}
          >
            Run all
          </button>
        </div>
      </div>
      {view.cards.length > 0 && (
        <div className="pf-cards">
          {view.cards.map((m) => (
            <TopCard key={m.id} metric={m} />
          ))}
        </div>
      )}
      {view.sections.some((s) => s.metrics.length > 0) && (
        <div className="pf-legend" aria-hidden="true">
          <span>
            <i className="pf-prev" />
            Previous run
          </span>
          <span>
            <i className="pf-now" />
            This run
          </span>
        </div>
      )}
      {main.map(card)}
      {more.length > 0 && (
        <section className="pf-adv">
          <button
            className="ft-row pf-advb"
            aria-expanded={advanced}
            onClick={() => {
              setAdvanced(!advanced);
            }}
          >
            <span className="ft-name">Advanced</span>
            <Icon name="chevr" className="ft-cv" />
          </button>
          {advanced && more.map(card)}
        </section>
      )}
      {view.changes.length > 0 && (
        <Section title="What changed">
          {view.changes.map((c) => (
            <div key={c.text} className="srow pf-change">
              <span className={`pf-tdot ${TONE[c.tone]}`} aria-hidden="true" />
              <span className="slab">{c.text}</span>
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}

function RunState({ view }: { view: PerfView }) {
  if (view.running !== null) {
    return (
      <>
        <span className="dot s-run" aria-hidden="true" />
        Running...
      </>
    );
  }
  if (view.last_run === null) return <>Never run</>;
  const at = activityTime(view.last_run.finished_at, new Date());
  return <>{`Last run ${at} · ${durationText(view.last_run.duration_ms)}`}</>;
}

function Change({ metric }: { metric: PerfMetric }) {
  if (metric.change === null) return <span className="pf-c" />;
  return <span className={`pf-c ${TONE[metric.change.tone]}`}>{metric.change.text}</span>;
}

/** One of the four numbers at the top: big, its change, then its parts. */
function TopCard({ metric }: { metric: PerfMetric }) {
  const parts = metric.parts ?? [];
  const stacked = parts.length > PART_LINES;
  return (
    <div className={stacked ? "pf-card pf-wide" : "pf-card"}>
      <span className="pf-cl">{metric.label}</span>
      <div className="pf-hl">
        <b className="pf-big">{metric.text}</b>
        <Change metric={metric} />
      </div>
      {stacked ? <Stack metric={metric} /> : null}
      {metric.sub !== null && <span className="pf-kv">{metric.sub}</span>}
      {!stacked &&
        parts.map((p) => (
          <span key={p.label} className="pf-kv">
            <span>{p.label}</span>
            <b>{p.text}</b>
          </span>
        ))}
    </div>
  );
}

/** A total's parts as one bar, each part its share of the total, and a key under it. */
function Stack({ metric }: { metric: PerfMetric }) {
  const parts = metric.parts ?? [];
  const sum = parts.reduce((n, p) => n + Math.max(0, p.value), 0);
  const rest = Math.max(0, (metric.value ?? 0) - sum);
  return (
    <>
      <div
        className="pf-stack"
        role="img"
        aria-label={parts.map((p) => `${p.label} ${p.text}`).join(", ")}
      >
        {parts.map((p, i) => (
          <i key={p.label} className={`pf-p${String(i % 8)}`} style={{ flexGrow: p.value }} />
        ))}
        {rest > 0 && <i className="pf-rest" style={{ flexGrow: rest }} />}
      </div>
      <div className="pf-key">
        {parts.map((p, i) => (
          <span key={p.label}>
            <i className={`pf-p${String(i % 8)}`} />
            {p.label} <b>{p.text}</b>
          </span>
        ))}
      </div>
    </>
  );
}

function SectionCard({
  section,
  running,
  disabled,
  onRun,
}: {
  section: PerfSection;
  running: boolean;
  disabled: boolean;
  onRun: () => void;
}) {
  const id = useId();
  const widths = barWidths(section.metrics);
  const empty = section.metrics.length === 0 && section.series === null;
  // The title alone names the section; its tools sit beside it, outside the heading.
  return (
    <section className={running ? "pf-sec pf-busy" : "pf-sec"} aria-labelledby={id}>
      <div className="pg-h pf-sh">
        <h2 id={id}>{section.title}</h2>
        <span className="pf-tools">
          {section.live && <span className="pf-live">Spends usage</span>}
          {running ? (
            <span className="sst run">
              <span className="dot s-run" aria-hidden="true" /> Running
            </span>
          ) : (
            section.runner !== "mac" && (
              <button
                className="lnk"
                aria-label={`Run ${section.title}`}
                disabled={disabled}
                onClick={onRun}
              >
                Run
              </button>
            )
          )}
        </span>
      </div>
      <div className="lgrp gl">
        {section.error !== null && <div className="srow note pf-err">{section.error}</div>}
        {section.series !== null && <Days series={section.series} />}
        {section.metrics.map((m) => (
          <MetricRow key={m.id} metric={m} widths={widths.get(m.id)} />
        ))}
        {empty && section.error === null && <div className="srow note">Not run yet</div>}
        {section.note !== null && !empty && <div className="srow note">{section.note}</div>}
      </div>
    </section>
  );
}

function MetricRow({
  metric,
  widths = { previous: 0, value: 0 },
}: {
  metric: PerfMetric;
  widths?: { previous: number; value: number } | undefined;
}) {
  const bars = [
    metric.previous_text === null ? null : `Previous run ${metric.previous_text}`,
    `This run ${metric.text}`,
  ].filter((part) => part !== null);
  return (
    <div className="srow pf-m">
      <span className="pf-ml">
        {metric.label}
        {metric.sub !== null && <span className="hint"> {metric.sub}</span>}
      </span>
      <span className="pf-v">{metric.text}</span>
      <Change metric={metric} />
      <span className="pf-bars" role="img" aria-label={bars.join(", ")}>
        {metric.previous !== null && (
          <i className="pf-prev" style={{ width: `${String(widths.previous)}%` }} />
        )}
        {metric.value !== null && (
          <i className="pf-now" style={{ width: `${String(widths.value)}%` }} />
        )}
      </span>
    </div>
  );
}

/** A series as one small bar a day, scaled to its busiest day. */
function Days({ series }: { series: PerfSeries }) {
  const top = Math.max(0, ...series.points.map((p) => p.value));
  return (
    <div
      className="srow pf-days"
      role="img"
      aria-label={`${series.label}: ${series.points.map((p) => `${p.day} ${String(p.value)}`).join(", ")}`}
    >
      {series.points.map((p) => (
        <i key={p.day} style={{ height: `${String(top > 0 ? (100 * p.value) / top : 0)}%` }} />
      ))}
    </div>
  );
}
