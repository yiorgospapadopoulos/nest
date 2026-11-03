import { Fragment, useEffect, useState } from "react";
import type { ReportSeverity } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { deviceStorage } from "../../../store/legacyKeys.ts";
import { useApi } from "../../context.ts";
import {
  loadPreferences,
  loadSound,
  NOTIFY_TOGGLES,
  savePreferences,
  saveSound,
  type NotificationPreferences,
} from "../../notifications.ts";
import { Segmented } from "../../ui/controls.tsx";
import { StatusLabel } from "../config/parts.tsx";
import { SettingsRow, SettingsSection, SwitchRow } from "../rows.tsx";

// The least severe pixie report that reaches the phone, in the Mac's words (B85).
const LEVELS: { value: ReportSeverity; label: string }[] = [
  { value: "info", label: "Info" },
  { value: "warn", label: "Warnings" },
  { value: "action", label: "Action" },
];

/**
 * What reaches this computer as a notification, as the Mac's page (AgentPages.swift); the
 * iPhone keeps its own choices, except which pixie reports it gets, kept on the daemon.
 */
export function NotificationsPage() {
  const storage = deviceStorage();
  const [preferences, setPreferences] = useState<NotificationPreferences>(() =>
    loadPreferences(storage),
  );
  const [sound, setSound] = useState(() => loadSound(storage));
  return (
    <>
      <SettingsSection title="Notify me about">
        {NOTIFY_TOGGLES.map(({ kind, title }) => (
          <Fragment key={kind}>
            <SwitchRow
              label={title}
              on={preferences[kind]}
              onChange={(on) => {
                const next = { ...preferences, [kind]: on };
                savePreferences(storage, next);
                setPreferences(next);
              }}
            />
            {kind === "pixie_report" && <PixieReportLevelRow />}
          </Fragment>
        ))}
      </SettingsSection>
      <SettingsSection title="Delivery">
        <SwitchRow
          label="Sound"
          on={sound}
          onChange={(on) => {
            saveSound(storage, on);
            setSound(on);
          }}
        />
        <PushRow />
      </SettingsSection>
    </>
  );
}

/** "On for 2 devices", "Off" with none, "-" before it was read (DevicesStore.pushText). */
function pushText(devices: number | null): string {
  if (devices === null) return "-";
  if (devices === 0) return "Off";
  return devices === 1 ? "On for 1 device" : `On for ${String(devices)} devices`;
}

/** How many iPhones get push notifications from this daemon, read when the page opens. */
function PushRow() {
  const api = useApi();
  const [devices, setDevices] = useState<number | null>(null);
  useEffect(() => {
    let current = true;
    api.pushStatus().then(
      (status) => {
        if (current) setDevices(status.devices);
      },
      () => undefined,
    );
    return () => {
      current = false;
    };
  }, [api]);
  const on = (devices ?? 0) > 0;
  return (
    <SettingsRow label="iPhone push">
      <StatusLabel tone={on ? "review" : "done"} label={pushText(devices)} hollow={!on} />
    </SettingsRow>
  );
}

/** Which pixie reports reach the iPhone, one level for every pixie (B85). */
function PixieReportLevelRow() {
  const { state, actions } = useStore();
  const rules = state.notifications;
  useEffect(() => {
    void actions.loadNotifications();
  }, [actions]);
  return (
    <SettingsRow label="Send to the phone from">
      <span className={rules === null ? "dks-off" : undefined}>
        <Segmented
          label="Send to the phone from"
          value={rules?.pixie_report_level ?? "action"}
          options={LEVELS}
          onChange={(pixie_report_level) => {
            if (rules !== null) {
              void actions.saveNotifications({ ...rules, pixie_report_level }, rules);
            }
          }}
        />
      </span>
    </SettingsRow>
  );
}
