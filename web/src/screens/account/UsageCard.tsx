import { useState } from "react";
import type { LimitWindow } from "../../api/types.ts";
import { clockTime, percent, resetLabel } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import { UsageCalendar } from "./UsageCalendar.tsx";

// Numbers older than this are shown dimmed.
const STALE_MS = 10 * 60_000;

/** The subscription windows Claude reports, and the month Nest counted itself. */
export function UsageCard() {
  const { state, actions } = useStore();
  const [refreshing, setRefreshing] = useState(false);
  const limits = state.limits;
  const now = new Date();

  const refresh = async () => {
    setRefreshing(true);
    await actions.refreshUsage();
    setRefreshing(false);
  };

  return (
    <section aria-labelledby="usage-title">
      <h2 className="pg-h" id="usage-title">
        Usage
        <button
          className="lnk"
          aria-label="Refresh usage"
          disabled={refreshing}
          onClick={() => void refresh()}
        >
          {refreshing ? "Refreshing..." : "Refresh"}
        </button>
      </h2>
      <div className="lgrp gl pad">
        <Meter label="5 hour window" window={limits?.five_hour ?? null} now={now} />
        <Meter label="Weekly" window={limits?.seven_day ?? null} now={now} />
        <UsageCalendar />
        <div className="note">
          Claude reports the 5 hour and weekly limits; Nest asks again every few minutes while it is
          open. Monthly and daily figures are counted by Nest.
        </div>
      </div>
    </section>
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
  const updated = new Date(window.updated_at);
  const stale = now.getTime() - updated.getTime() > STALE_MS;
  return (
    <div className="urow">
      <div className="u1">
        <span>{label}</span>
        <b>{used}%</b>
      </div>
      <div
        className="meter"
        role="meter"
        aria-label={`${label} used`}
        aria-valuenow={used}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <i style={{ width: `${String(used)}%` }} />
      </div>
      <div className="u2">
        <span>{resetLabel(window.resets_at, now)}</span>
        <span
          className={stale ? "asof stale" : "asof"}
          title={stale ? "More than 10 minutes old" : undefined}
        >
          as of {clockTime(updated)}
        </span>
      </div>
    </div>
  );
}
