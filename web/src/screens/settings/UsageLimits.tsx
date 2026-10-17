import { useState } from "react";
import type { LimitWindow, UsageSettings } from "../../api/types.ts";
import { clockTime, percent, resetLabel } from "../../format.ts";
import { useStore } from "../../store/context.ts";
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
 * The subscription windows Claude reports, the periods Nest counted itself (B84), and when
 * the Mac checks the windows and warns (D104).
 */
export function UsageLimits({ onDetails }: { onDetails: () => void }) {
  const { state, actions } = useStore();
  const [refreshing, setRefreshing] = useState(false);
  const limits = state.limits;
  const settings = state.settings.usage;
  const now = new Date();

  const refresh = async () => {
    setRefreshing(true);
    await actions.refreshUsage();
    setRefreshing(false);
  };

  // One time for both windows: the older report, so a stale one shows.
  const reported = [limits?.five_hour, limits?.seven_day]
    .filter((w): w is LimitWindow => w != null)
    .map((w) => new Date(w.updated_at))
    .sort((a, b) => a.getTime() - b.getTime())[0];
  const stale = reported !== undefined && now.getTime() - reported.getTime() > STALE_MS;

  return (
    <>
      <Section
        title="Usage"
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
          <Meter label="5 hour" window={limits?.five_hour ?? null} now={now} />
          <Meter label="Weekly" window={limits?.seven_day ?? null} now={now} />
        </div>
      </Section>
      <UsagePeriodCard onDetails={onDetails} />
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

function Meter({ label, window, now }: { label: string; window: LimitWindow | null; now: Date }) {
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
  const used = percent(window.utilization);
  return (
    <div className="urow">
      <div className="u1">
        <span>{label}</span>
        <b>{used}%</b>
      </div>
      <div
        className="meter sm ink"
        role="meter"
        aria-label={`${label} used`}
        aria-valuenow={used}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <i style={{ width: `${String(used)}%` }} />
      </div>
      <div className="u2">{resetLabel(window.resets_at, now)}</div>
    </div>
  );
}
