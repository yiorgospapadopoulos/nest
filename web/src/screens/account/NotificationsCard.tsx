import { useEffect, useState } from "react";
import type { NotificationSettings, QuietHours } from "../../api/types.ts";
import { browserPushEnv, pushStatus, type PushStatus } from "../../pwa/push.ts";
import { useStore } from "../../store/context.ts";
import { Pill } from "../../ui/bits.tsx";
import { KINDS } from "./notifyKinds.ts";

const DEFAULT_QUIET: QuietHours = { start: "22:00", end: "07:00" };

const HINTS: Partial<Record<PushStatus, string>> = {
  install:
    "Add Nest to your Home Screen first: tap Share, then Add to Home Screen, and open it from there.",
  unsupported: "This browser cannot show notifications.",
  denied: "Notifications are blocked. Allow them for Nest in Settings, Notifications.",
};

/** This device's push subscription, and the daemon's rules shared by every device. */
export function NotificationsCard() {
  const { state, actions } = useStore();
  const [env] = useState(() => browserPushEnv(window));
  const [status, setStatus] = useState<PushStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const settings = state.notifications;

  useEffect(() => {
    let live = true;
    void pushStatus(env).then((found) => {
      if (live) setStatus(found);
    });
    return () => {
      live = false;
    };
  }, [env]);

  useEffect(() => {
    void actions.loadNotifications();
  }, [actions]);

  const run = async (work: () => Promise<PushStatus | null>) => {
    setBusy(true);
    const next = await work();
    setBusy(false);
    if (next !== null) setStatus(next);
  };

  return (
    <section aria-labelledby="notifications-title">
      <h2 className="pg-h" id="notifications-title">
        Notifications
      </h2>
      <div className="lgrp gl">
        <div className={`srow${status !== null && status in HINTS ? " col" : ""}`}>
          <span>This device</span>
          {status === null && <span className="hint">Checking...</span>}
          {status !== null && status in HINTS && <span className="hint">{HINTS[status]}</span>}
          {status === "off" && (
            <button
              className="b b-pri"
              disabled={busy}
              onClick={() => void run(() => actions.enablePush(env))}
            >
              Enable notifications
            </button>
          )}
          {status === "on" && <Pill tone="rev" label="On" />}
        </div>
        {status === "on" && (
          <div className="srow">
            <button className="b" disabled={busy} onClick={() => void actions.testPush()}>
              Send test
            </button>
            <button
              className="b"
              disabled={busy}
              onClick={() => void run(() => actions.disablePush(env))}
            >
              Turn off
            </button>
          </div>
        )}
      </div>
      {settings === null ? (
        <div className="lgrp gl pad note">Loading...</div>
      ) : (
        <Rules settings={settings} />
      )}
    </section>
  );
}

/** Which kinds reach the phone, and quiet hours; saved to the Mac at once. */
function Rules({ settings }: { settings: NotificationSettings }) {
  const { actions } = useStore();
  const save = (change: Partial<NotificationSettings>) => {
    void actions.saveNotifications({ ...settings, ...change }, settings);
  };
  return (
    <>
      <h3 className="pg-h">Notify me about</h3>
      <div className="lgrp gl">
        {KINDS.map(({ kind, label }) => (
          <Switch
            key={kind}
            id={`notify-${kind}`}
            label={label}
            on={settings.kinds[kind]}
            onToggle={() => {
              save({ kinds: { ...settings.kinds, [kind]: !settings.kinds[kind] } });
            }}
          />
        ))}
        <Switch
          id="notify-quiet"
          label="Quiet hours"
          on={settings.quiet_hours !== null}
          onToggle={() => {
            save({ quiet_hours: settings.quiet_hours === null ? DEFAULT_QUIET : null });
          }}
        />
        {settings.quiet_hours !== null && (
          <QuietHoursRow
            quiet={settings.quiet_hours}
            onChange={(quiet_hours) => {
              save({ quiet_hours });
            }}
          />
        )}
      </div>
      <div className="note gnote">
        These rules apply to every paired device. Quiet hours follow your Mac&apos;s clock.
      </div>
    </>
  );
}

function Switch({
  id,
  label,
  on,
  onToggle,
}: {
  id: string;
  label: string;
  on: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="srow">
      <span id={id}>{label}</span>
      <button
        className="sw"
        role="switch"
        aria-checked={on}
        aria-labelledby={id}
        onClick={onToggle}
      />
    </div>
  );
}

function QuietHoursRow({
  quiet,
  onChange,
}: {
  quiet: QuietHours;
  onChange: (quiet: QuietHours) => void;
}) {
  const set = (field: keyof QuietHours, value: string) => {
    const next = { ...quiet, [field]: value };
    // An empty or zero-length window is refused by the Mac; keep the last good one.
    if (value !== "" && next.start !== next.end) onChange(next);
  };
  return (
    <div className="srow qh">
      <label>
        From
        <input
          type="time"
          value={quiet.start}
          onChange={(event) => {
            set("start", event.target.value);
          }}
        />
      </label>
      <label>
        Until
        <input
          type="time"
          value={quiet.end}
          onChange={(event) => {
            set("end", event.target.value);
          }}
        />
      </label>
    </div>
  );
}
