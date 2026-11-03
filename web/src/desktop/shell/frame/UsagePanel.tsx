import { useEffect, useState, type ReactNode } from "react";
import type { AccountWindow, PeriodUnit, UsageBar, UsagePeriod } from "../../../api/types.ts";
import { clockTime, tokens } from "../../../format.ts";
import { resetLine, used } from "../../../screens/settings/accountText.ts";
import {
  barHeight,
  barTip,
  chatCount,
  isoDay,
  periodRange,
  periodTitle,
  probesLine,
  projectRows,
  share,
  stepDate,
  ticks,
  UNITS,
} from "../../../screens/settings/usageText.ts";
import { useUsage } from "../../../screens/settings/useUsage.ts";
import { useStore } from "../../../store/context.ts";
import { engineName } from "../../../store/selectors.ts";
import { limitGroups } from "../../../store/usageMeter.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Icon } from "../../../ui/Icon.tsx";
import { Button, Segmented } from "../../ui/controls.tsx";
import { useMinute } from "./clock.ts";
import { EngineMark } from "./marks.tsx";

// Limits reported longer ago than this read as old on Refresh.
const STALE_MS = 10 * 60_000;

/**
 * The usage panel, as the Mac's UsagePanel (B84, B98): the limits of each account the top
 * bar shows with a Refresh that says when they were reported, then a day, week, month or
 * year of tokens as bars, the totals and Details, which swaps in the breakdown. The usage
 * popover shows it at 340 px; Settings > Usage can show it too.
 */
export function UsagePanel({ title }: { title: string }) {
  const [details, setDetails] = useState(false);
  const today = useMinute();
  const usage = useUsage(today);
  return (
    <div className="fr-usage">
      {details ? (
        <Breakdown
          {...usage}
          today={today}
          onBack={() => {
            setDetails(false);
          }}
        />
      ) : (
        <Chart
          title={title}
          {...usage}
          today={today}
          onDetails={() => {
            setDetails(true);
          }}
        />
      )}
    </div>
  );
}

interface PeriodProps {
  unit: PeriodUnit;
  date: string;
  period: UsagePeriod | null;
  today: Date;
}

function Chart({
  title,
  unit,
  date,
  period,
  today,
  onDetails,
}: PeriodProps & { title: string; onDetails: () => void }) {
  const { state, actions } = useStore();
  const { accounts, usageMeter } = state.settings;
  const groups = accounts === null ? [] : limitGroups(accounts, usageMeter);
  const current = period?.current ?? periodRange(unit, date).end >= isoDay(today);
  const amount = (n: number | undefined) => (n === undefined ? "-" : tokens(n));
  useEffect(() => {
    if (accounts === null) void actions.loadAccounts();
  }, [accounts, actions]);
  return (
    <>
      <div className="fr-uhead">
        <b>{title}</b>
        <Refresh windows={groups.flatMap((g) => g.limits)} now={today} />
      </div>
      {accounts === null && <p className="fr-unote">Loading</p>}
      {groups.map((group) => (
        <section key={group.id} className="fr-ugroup" aria-label={group.title}>
          <h3>
            <EngineMark provider={group.provider} size={12} />
            <span>{group.title}</span>
            {group.active && <small>in use</small>}
          </h3>
          {group.limits.length === 0 ? (
            <Limit title="Usage" window={null} now={today} />
          ) : (
            group.limits.map((w) => <Limit key={w.label} title={w.label} window={w} now={today} />)
          )}
        </section>
      ))}
      <hr className="fr-usep" />
      <Segmented
        label="Period"
        value={unit}
        options={UNITS.map((u) => ({ value: u.value, label: u.label }))}
        onChange={(value) => {
          actions.viewUsage(value, null);
        }}
      />
      <div className="fr-unav">
        <Button
          kind="plain"
          iconOnly
          aria-label="Previous"
          onClick={() => {
            actions.viewUsage(unit, stepDate(unit, date, -1));
          }}
        >
          <Icon name="chevl" />
        </Button>
        <b aria-live="polite">{periodTitle(unit, date, today)}</b>
        <Button
          kind="plain"
          iconOnly
          aria-label="Next"
          disabled={current}
          onClick={() => {
            actions.viewUsage(unit, stepDate(unit, date, 1));
          }}
        >
          <Icon name="chevr" />
        </Button>
      </div>
      <Bars key={`${unit} ${date}`} unit={unit} bars={period?.bars ?? []} date={date} now={today} />
      <div className="fr-utot">
        <Line label="Chats">
          {amount(period === null ? undefined : period.tokens.total - period.subagents.total)}
        </Line>
        <Line label="Subagents">{amount(period?.subagents.total)}</Line>
        <Line label={period === null ? "Total" : `Total · ${chatCount(period.sessions)}`} total>
          {amount(period?.tokens.total)}
        </Line>
      </div>
      <Button kind="plain" className="fr-udet" onClick={onDetails}>
        Details
        <Icon name="chevr" />
      </Button>
    </>
  );
}

/** "as of 14:05" with its refresh mark, dimmed once the limits are 10 minutes old. */
function Refresh({ windows, now }: { windows: AccountWindow[]; now: Date }) {
  const { actions } = useStore();
  const [refreshing, setRefreshing] = useState(false);
  const reported = windows
    .map((w) => new Date(w.updated_at))
    .sort((a, b) => b.getTime() - a.getTime())[0];
  const stale = reported !== undefined && now.getTime() - reported.getTime() > STALE_MS;
  return (
    <Button
      kind="plain"
      className="fr-urefresh"
      disabled={refreshing}
      title={stale ? "More than 10 minutes old. Ask for the limits now" : "Ask for the limits now"}
      onClick={() => {
        setRefreshing(true);
        void actions.refreshAccounts().finally(() => {
          setRefreshing(false);
        });
      }}
    >
      {refreshing ? <Fireflies size={9} /> : <Icon name="restart" />}
      <span className={stale ? "stale" : undefined}>
        {reported === undefined ? "Refresh" : `as of ${clockTime(reported)}`}
      </span>
    </Button>
  );
}

/** A limit's name and percent, a 3 px bar and when it resets. */
function Limit({ title, window, now }: { title: string; window: AccountWindow | null; now: Date }) {
  const percent = window === null ? 0 : used(window);
  return (
    <div className="fr-ulimit">
      <div>
        <span>{title}</span>
        <b>{window === null ? "-" : `${String(percent)}%`}</b>
      </div>
      <span className="fr-umeter" aria-hidden="true">
        <i style={{ width: `${String(percent)}%` }} />
      </span>
      <small>{window === null ? "Not reported yet" : resetLine(window, now)}</small>
    </div>
  );
}

function Line({
  label,
  total = false,
  children,
}: {
  label: string;
  total?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={total ? "fr-uline total" : "fr-uline"}>
      <span>{label}</span>
      <b>{children}</b>
    </div>
  );
}

/** The period's bars scaled to the busiest, ticks below; hovering a bar shows its numbers. */
function Bars({
  unit,
  bars,
  date,
  now,
}: {
  unit: PeriodUnit;
  bars: UsageBar[];
  date: string;
  now: Date;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const peak = Math.max(0, ...bars.map((b) => b.tokens));
  const tip = hovered === null ? undefined : bars[hovered];
  return (
    <div className="fr-ubars">
      {tip !== undefined && (
        <span
          className="fr-utip"
          style={{
            left: `${String(Math.min(80, Math.max(20, ((hovered ?? 0) / bars.length) * 100)))}%`,
          }}
        >
          {barTip(unit, tip)}
        </span>
      )}
      <div className="fr-ucols" role="group" aria-label="Tokens over the period">
        {bars.map((bar, index) => {
          const future = new Date(bar.start).getTime() > now.getTime();
          const kind = future ? "fut" : bar.tokens > 0 ? "on" : "";
          return (
            <span
              key={bar.start}
              className={hovered === null || hovered === index ? "fr-ucol" : "fr-ucol dim"}
              role="img"
              aria-label={barTip(unit, bar)}
              onPointerEnter={() => {
                setHovered(index);
              }}
              onPointerLeave={() => {
                setHovered((h) => (h === index ? null : h));
              }}
            >
              <i className={kind} style={{ height: `${String(barHeight(bar.tokens, peak))}px` }} />
            </span>
          );
        })}
      </div>
      <div className="fr-uticks">
        {ticks(unit, date).map((t) => (
          <span key={t}>{t}</span>
        ))}
      </div>
    </div>
  );
}

/** The period's tokens by engine, by who, by kind and by project; ‹ goes back. */
function Breakdown({ unit, date, period, today, onBack }: PeriodProps & { onBack: () => void }) {
  const { state } = useStore();
  const rows = (items: { label: string; value: number; of: number }[]) => (
    <div className="fr-ushare">
      {items.map((item) => (
        <div key={item.label}>
          <span>{item.label}</span>
          <b>{tokens(item.value)}</b>
          <small>{share(item.value, item.of)}</small>
        </div>
      ))}
    </div>
  );
  const total = period?.tokens.total ?? 0;
  const engines = period?.engines ?? [];
  const counted = engines.reduce((sum, e) => sum + e.tokens, 0);
  const projects = period === null ? [] : projectRows(period.projects);
  const peak = projects[0]?.tokens ?? 0;
  const probes = period === null ? null : probesLine(period.probes);
  return (
    <>
      <div className="fr-uhead back">
        <Button kind="plain" iconOnly aria-label="Back" onClick={onBack}>
          <Icon name="chevl" />
        </Button>
        <b>{periodTitle(unit, date, today)}</b>
        <b className="fr-uright">{period === null ? "-" : tokens(total)}</b>
      </div>
      {period === null ? (
        <p className="fr-unote">Loading</p>
      ) : (
        <>
          {engines.length > 0 && (
            <>
              <h4 className="fr-uh">By engine</h4>
              {rows(
                engines.map((e) => ({
                  label: engineName(state, e.provider),
                  value: e.tokens,
                  of: counted,
                })),
              )}
            </>
          )}
          <h4 className="fr-uh">By who</h4>
          {rows([
            { label: "Chats", value: total - period.subagents.total, of: total },
            { label: "Subagents", value: period.subagents.total, of: total },
          ])}
          <h4 className="fr-uh">By kind</h4>
          {rows([
            { label: "Cache read", value: period.tokens.cache_read_input_tokens, of: total },
            { label: "Cache write", value: period.tokens.cache_creation_input_tokens, of: total },
            { label: "Output", value: period.tokens.output_tokens, of: total },
            { label: "Input", value: period.tokens.input_tokens, of: total },
          ])}
          {projects.length > 0 && (
            <>
              <h4 className="fr-uh">By project</h4>
              <div className="fr-uprojects">
                {projects.map((p) => (
                  <div key={p.name}>
                    <div>
                      <span>{p.name}</span>
                      <b>{tokens(p.tokens)}</b>
                    </div>
                    <span className="fr-umeter soft" aria-hidden="true">
                      <i style={{ width: `${String(peak > 0 ? (100 * p.tokens) / peak : 0)}%` }} />
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
          {probes !== null && <p className="fr-unote">{probes}</p>}
        </>
      )}
    </>
  );
}
