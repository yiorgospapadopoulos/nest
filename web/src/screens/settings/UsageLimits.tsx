import { useEffect, useState, type PointerEvent } from "react";
import type { AccountWindow, UsageSettings } from "../../api/types.ts";
import { clockTime } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import { limitGroups, meterEntries, movedTo, type MeterAccount } from "../../store/usageMeter.ts";
import { Icon } from "../../ui/Icon.tsx";
import { resetLine, used } from "./accountText.ts";
import { Loading, Section, SelectRow, SwitchRow } from "./rows.tsx";
import { withCurrent } from "./choices.ts";
import { UsagePeriodCard } from "./UsagePeriodCard.tsx";

// Numbers older than this are shown dimmed.
const STALE_MS = 10 * 60_000;

// How often the Mac checks the limits while a client is open, in minutes; 0 is off.
const REFRESH = [0, 1, 3, 5, 10, 15];
// Warn at this share of a limit; null is off (D104).
const WARN = [70, 80, 90];

function refreshLabel(minutes: number): string {
  if (minutes === 0) return "Off";
  return minutes === 1 ? "Every minute" : `Every ${String(minutes)} minutes`;
}

/**
 * The limits of each account the top bar shows (B98: by default the account in use of each
 * engine), the periods Nest counted itself (B84), which accounts the top bar shows and in
 * which order, and when the Mac checks the windows and warns (D104). Every account's windows
 * come with `GET /api/accounts`, so none waits for the engine list (I-B111-1).
 */
export function UsageLimits({ onDetails }: { onDetails: () => void }) {
  const { state, actions } = useStore();
  const [refreshing, setRefreshing] = useState(false);
  const { accounts, usageMeter } = state.settings;
  const settings = state.settings.usage;
  const now = new Date();
  const groups = accounts === null ? [] : limitGroups(accounts, usageMeter);

  useEffect(() => {
    void actions.loadAccounts();
  }, [actions]);

  const refresh = async () => {
    setRefreshing(true);
    await actions.refreshAccounts();
    setRefreshing(false);
  };

  // The newest report of the windows shown.
  const reported = groups
    .flatMap((g) => g.limits)
    .map((w) => new Date(w.updated_at))
    .sort((a, b) => b.getTime() - a.getTime())[0];
  const stale = reported !== undefined && now.getTime() - reported.getTime() > STALE_MS;

  return (
    <>
      <Section
        title="Limits"
        tools={
          <>
            {reported !== undefined && (
              <span
                className={stale ? "uasof asof stale" : "uasof asof"}
                title={stale ? "More than 10 minutes old" : undefined}
              >
                as of {clockTime(reported)}
              </span>
            )}
            <button
              className="lnk ulnk"
              aria-label="Refresh usage"
              disabled={refreshing}
              onClick={() => void refresh()}
            >
              {refreshing ? "Refreshing..." : "Refresh"}
            </button>
          </>
        }
      >
        <div className="pad">
          {accounts === null && <p className="note">Loading...</p>}
          {groups.map((group) => (
            <div key={group.id}>
              <h3 className="ueng">
                {group.title}
                {group.active && (
                  <>
                    {" "}
                    <span className="uinuse">in use</span>
                  </>
                )}
              </h3>
              {group.limits.length === 0 && <Meter label="Usage" window={null} now={now} />}
              {group.limits.map((w) => (
                <Meter
                  key={w.label}
                  label={w.label}
                  name={`${group.title} ${w.label}`}
                  window={w}
                  now={now}
                />
              ))}
            </div>
          ))}
        </div>
      </Section>
      <UsagePeriodCard onDetails={onDetails} />
      <TopBar />
      {settings === null ? <Loading /> : <Checks settings={settings} />}
    </>
  );
}

function Checks({ settings }: { settings: UsageSettings }) {
  const { actions } = useStore();
  const save = (change: Partial<UsageSettings>) =>
    void actions.saveSection("usage", { ...settings, ...change }, settings);
  const warn = settings.warn_percent;
  return (
    <Section className="useq">
      <SelectRow
        label="Check limits"
        value={settings.refresh_minutes}
        choices={withCurrent(REFRESH, settings.refresh_minutes).map((m) => ({
          value: m,
          label: refreshLabel(m),
        }))}
        onChange={(refresh_minutes) => {
          save({ refresh_minutes });
        }}
      />
      <SelectRow<number | null>
        label="Warn me at"
        value={warn}
        choices={[
          ...(warn === null ? WARN : withCurrent(WARN, warn)).map((p) => ({
            value: p,
            label: `${String(p)}%`,
          })),
          { value: null, label: "Off" },
        ]}
        onChange={(warn_percent) => {
          save({ warn_percent });
        }}
      />
      <SwitchRow
        label="Also as a notification"
        on={settings.warn_notify}
        disabled={warn === null}
        onToggle={() => {
          save({ warn_notify: !settings.warn_notify });
        }}
      />
    </Section>
  );
}

// A drag starts moving its row past this many pixels.
const DRAG_SLOP = 4;

/**
 * Which accounts the top bar shows and in which order, on this device only (B98): a check
 * per account; its handle drags it, or the arrow keys move it while the handle has focus.
 */
function TopBar() {
  const { state, actions } = useStore();
  const { accounts, usageMeter } = state.settings;
  const entries = accounts === null ? [] : meterEntries(accounts, usageMeter);
  const ids = entries.map((e) => e.id);
  // The row being dragged: where it started, the pointer's start and travel, a row's height.
  const [drag, setDrag] = useState<{
    id: string;
    from: number;
    startY: number;
    dy: number;
    step: number;
  } | null>(null);

  const target = (from: number, dy: number, step: number) =>
    Math.max(0, Math.min(ids.length - 1, from + Math.round(dy / step)));

  const move = (from: number, to: number) => {
    if (from !== to) actions.orderUsageMeter(movedTo(ids, from, to));
  };

  const onDown = (event: PointerEvent<HTMLButtonElement>, id: string, from: number) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    const step = event.currentTarget.closest(".srow")?.getBoundingClientRect().height ?? 0;
    setDrag({ id, from, startY: event.clientY, dy: 0, step: step > 0 ? step : 44 });
  };
  const onMove = (event: PointerEvent<HTMLButtonElement>) => {
    if (drag === null) return;
    setDrag({ ...drag, dy: event.clientY - drag.startY });
  };
  const onUp = () => {
    if (drag === null) return;
    if (Math.abs(drag.dy) > DRAG_SLOP) move(drag.from, target(drag.from, drag.dy, drag.step));
    setDrag(null);
  };

  // The rows the dragged one passes slide aside by one row.
  const offset = (index: number) => {
    if (drag === null) return 0;
    if (index === drag.from) return drag.dy;
    const to = target(drag.from, drag.dy, drag.step);
    if (drag.from < index && index <= to) return -drag.step;
    if (to <= index && index < drag.from) return drag.step;
    return 0;
  };

  if (accounts === null) return <Loading title="Top bar shows" />;
  return (
    <Section title="Top bar shows">
      {entries.map((entry, index) => (
        <MeterRow
          key={entry.id}
          entry={entry}
          dragged={drag?.id === entry.id}
          offset={offset(index)}
          onDown={(event) => {
            onDown(event, entry.id, index);
          }}
          onMove={onMove}
          onUp={onUp}
          onStep={(step) => {
            move(index, Math.max(0, Math.min(ids.length - 1, index + step)));
          }}
          onToggle={() => {
            actions.setUsageMeterShown(entry.id, !entry.shown, entries);
          }}
        />
      ))}
    </Section>
  );
}

function MeterRow({
  entry,
  dragged,
  offset,
  onDown,
  onMove,
  onUp,
  onStep,
  onToggle,
}: {
  entry: MeterAccount;
  dragged: boolean;
  offset: number;
  onDown: (event: PointerEvent<HTMLButtonElement>) => void;
  onMove: (event: PointerEvent<HTMLButtonElement>) => void;
  onUp: () => void;
  onStep: (step: -1 | 1) => void;
  onToggle: () => void;
}) {
  return (
    <div
      className={dragged ? "srow umrow drag" : "srow umrow"}
      style={offset === 0 ? undefined : { transform: `translateY(${String(offset)}px)` }}
    >
      <button
        className="umgrip"
        aria-label={`Move ${entry.name}`}
        aria-description="Drag, or use the up and down arrow keys"
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
        onKeyDown={(event) => {
          if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
          event.preventDefault();
          onStep(event.key === "ArrowUp" ? -1 : 1);
        }}
      >
        <Icon name="lines" />
      </button>
      <span className="slab">{entry.name}</span>
      <div className="sctl">
        {entry.detail !== "" && <span className="sval">{entry.detail}</span>}
        <button
          className="ucheck"
          role="checkbox"
          aria-checked={entry.shown}
          aria-label={`Show ${entry.name} in the top bar`}
          onClick={onToggle}
        />
      </div>
    </div>
  );
}

function Meter({
  label,
  name = label,
  window,
  now,
}: {
  label: string;
  // The meter's accessible name before "used", starting with the account's.
  name?: string;
  window: AccountWindow | null;
  now: Date;
}) {
  if (window === null) {
    return (
      <div className="urow">
        <div className="u1">
          <span>{label}</span>
          <b>Not reported yet</b>
        </div>
      </div>
    );
  }
  const percent = used(window);
  return (
    <div className="urow">
      <div className="u1">
        <span>{label}</span>
        <b>{percent}%</b>
      </div>
      <div
        className="meter sm ink"
        role="meter"
        aria-label={`${name} used`}
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <i style={{ width: `${String(percent)}%` }} />
      </div>
      <div className="u2">{resetLine(window, now)}</div>
    </div>
  );
}
