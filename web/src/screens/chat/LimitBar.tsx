import { useEffect, useState } from "react";
import type { AutopilotRun, LimitPause, Session } from "../../api/types.ts";
import { countdown, resetLabel } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { runLine, stepLine } from "./useAutopilot.ts";

// The limit's words in "Paused at the 5-hour usage limit"; others read "usage" alone.
const WINDOWS: Readonly<Record<string, string>> = {
  five_hour: "5-hour usage",
  seven_day: "weekly",
  seven_day_opus: "weekly Opus",
  seven_day_sonnet: "weekly Sonnet",
  overage: "extra usage",
};

/**
 * Just above the composer while the chat is paused at a usage limit (B78): which limit,
 * when it resets, a live countdown to when the daemon goes on, and Resume now.
 */
export function LimitBar({ session }: { session: Session }) {
  if (session.limit_pause === null) return null;
  // A new pause starts with its button ready.
  return <Bar key={session.limit_pause.since} id={session.id} pause={session.limit_pause} />;
}

function Bar({ id, pause }: { id: string; pause: LimitPause }) {
  const { state, actions } = useStore();
  const [busy, setBusy] = useState(false);
  const now = useNow();
  const waiting = (state.queued[id] ?? []).filter((m) => !m.sent).length;
  const words = (pause.window === null ? undefined : WINDOWS[pause.window]) ?? "usage";
  const goes = pause.resets_at === null ? "tries again" : "goes on";
  const left = countdown(Date.parse(pause.resume_at) - now);
  const resume = () => {
    setBusy(true);
    void actions.resumeLimit(id).then(() => {
      setBusy(false);
    });
  };
  return (
    <div className="lmw">
      <div className="lmbar gl" role="group" aria-label="Paused at the usage limit">
        <Dot tone="int" />
        <div className="lmt">
          <b>Paused at the {words} limit</b>
          <span>
            {resetLabel(pause.resets_at, new Date(now))} · {goes} {left}
          </span>
          <span>{queuedLine(waiting)}</span>
        </div>
        <button className="b" disabled={busy} onClick={resume}>
          Resume now
        </button>
      </div>
    </div>
  );
}

/** Just above the composer while the chat runs on Autopilot (B120), with Turn off. */
export function AutopilotBar({ session }: { session: Session }) {
  if (session.autopilot == null) return null;
  // A new run starts with its button ready.
  return <RunBar key={session.autopilot.started_at} id={session.id} run={session.autopilot} />;
}

function RunBar({ id, run }: { id: string; run: AutopilotRun }) {
  const { state, actions } = useStore();
  const [busy, setBusy] = useState(false);
  const now = useNow();
  const step = stepLine(state.tracking[id]?.tasks ?? []);
  const turnOff = () => {
    setBusy(true);
    void actions.setAutopilot(id, { on: false }).then(() => {
      setBusy(false);
    });
  };
  return (
    <div className="lmw">
      <div className="lmbar gl lmap" role="group" aria-label="Autopilot">
        <Icon name="infinity" />
        <div className="lmt">
          <b>Autopilot</b>
          {step !== null && <span>{step}</span>}
          <span>{runLine(run, now)}</span>
        </div>
        <button className="b" disabled={busy} onClick={turnOff}>
          Turn off
        </button>
      </div>
    </div>
  );
}

function queuedLine(waiting: number): string {
  if (waiting === 0) return "Then it continues where it left off.";
  if (waiting === 1) return "Your queued message sends then.";
  return `Your ${String(waiting)} queued messages send then.`;
}

/** The clock, read again every second. */
function useNow(): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => {
      clearInterval(timer);
    };
  }, []);
  return now;
}
