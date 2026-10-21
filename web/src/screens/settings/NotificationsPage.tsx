import { Fragment, useEffect, useState } from "react";
import type { NotificationSettings, QuietHours, ReportSeverity } from "../../api/types.ts";
import { browserPushEnv, pushStatus, type PushStatus } from "../../pwa/push.ts";
import { useStore } from "../../store/context.ts";
import { KINDS } from "./notifyKinds.ts";
import { Loading, Section, SelectRow, Status, SwitchRow } from "./rows.tsx";

const DEFAULT_QUIET: QuietHours = { start: "22:00", end: "07:00" };

const HINTS: Partial<Record<PushStatus, string>> = {
  install: "Add Nest to the Home Screen first",
  unsupported: "Not available in this browser",
  denied: "Blocked in iPhone Settings",
};

/** The daemon's rules shared by every device, then this device's push subscription. */
export function NotificationsPage() {
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
    <>
      {settings === null ? <Loading title="Notify me about" /> : <Kinds settings={settings} />}
      <Section title="Delivery">
        <div className="srow">
          <span>iPhone push</span>
          {status === null && <span className="sval">Checking...</span>}
          {status !== null && status in HINTS && <span className="sval">{HINTS[status]}</span>}
          {status === "off" && (
            <button
              className="b b-pri"
              disabled={busy}
              onClick={() => void run(() => actions.enablePush(env))}
            >
              Enable notifications
            </button>
          )}
          {status === "on" && <Status tone="ok" label="On" />}
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
        {settings !== null && <Quiet settings={settings} />}
      </Section>
    </>
  );
}

// The least severe pixie report that reaches the phone, in the Mac's short words (B85).
const LEVELS: { value: ReportSeverity; label: string }[] = [
  { value: "info", label: "Info" },
  { value: "warn", label: "Warnings" },
  { value: "action", label: "Action" },
];

/**
 * Which kinds reach the phone, and under Pixie reports the least severe one that does, for
 * every pixie (B85); saved to the Mac at once.
 */
function Kinds({ settings }: { settings: NotificationSettings }) {
  const { actions } = useStore();
  const save = (change: Partial<NotificationSettings>) => {
    void actions.saveNotifications({ ...settings, ...change }, settings);
  };
  return (
    <Section title="Notify me about">
      {KINDS.map(({ kind, label }) => (
        <Fragment key={kind}>
          <SwitchRow
            label={label}
            on={settings.kinds[kind]}
            onToggle={() => {
              save({ kinds: { ...settings.kinds, [kind]: !settings.kinds[kind] } });
            }}
          />
          {kind === "pixie_report" && (
            <SelectRow<ReportSeverity>
              label="Send to the phone from"
              value={settings.pixie_report_level}
              choices={LEVELS}
              disabled={!settings.kinds.pixie_report}
              onChange={(pixie_report_level) => {
                save({ pixie_report_level });
              }}
            />
          )}
        </Fragment>
      ))}
    </Section>
  );
}

/** Quiet hours, by the Mac's clock. */
function Quiet({ settings }: { settings: NotificationSettings }) {
  const { actions } = useStore();
  const save = (change: Partial<NotificationSettings>) => {
    void actions.saveNotifications({ ...settings, ...change }, settings);
  };
  return (
    <>
      <SwitchRow
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
    </>
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
