import { useEffect, useState } from "react";
import type { NotificationSettings } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { TextField } from "../ui/controls.tsx";
import { SettingsRow, SettingsSection, SwitchRow, WarningLine } from "./rows.tsx";

type Ntfy = NotificationSettings["ntfy"];

const WARNING = "Anyone who knows a public topic can read it. Use a long, random one.";

/** What a field's text is saved as: an emptied optional field is none. */
const text = (value: string | null) => value ?? "";
const optional = (value: string) => (value.trim() === "" ? null : value.trim());

function Field({
  label,
  value,
  placeholder,
  onSave,
}: {
  label: string;
  value: string;
  placeholder?: string;
  onSave: (value: string) => void;
}) {
  const [typed, setTyped] = useState<string | null>(null);
  return (
    <SettingsRow label={label}>
      <TextField
        label={label}
        className="dks-ntfy"
        value={typed ?? value}
        {...(placeholder === undefined ? {} : { placeholder })}
        onChange={setTyped}
        onBlur={() => {
          if (typed !== null && typed !== value) onSave(typed);
          setTyped(null);
        }}
      />
    </SettingsRow>
  );
}

/** ntfy's switch and fields, saved on the daemon as they change; a refused one goes back. */
export function NtfyFields() {
  const { state, actions } = useStore();
  const rules = state.notifications;
  useEffect(() => {
    void actions.loadNotifications();
  }, [actions]);
  if (rules === null) return null;
  const { ntfy } = rules;
  const save = (change: Partial<Ntfy>) => {
    void actions.saveNotifications({ ...rules, ntfy: { ...ntfy, ...change } }, rules);
  };
  return (
    <div className="dks-rows">
      <SwitchRow
        label="Send to ntfy"
        on={ntfy.enabled}
        onChange={(enabled) => {
          save({ enabled });
        }}
      />
      <Field
        label="Server"
        value={ntfy.server}
        onSave={(server) => {
          save({ server: server.trim() });
        }}
      />
      <Field
        label="Topic"
        value={text(ntfy.topic)}
        onSave={(topic) => {
          save({ topic: optional(topic) });
        }}
      />
      <Field
        label="Link address"
        value={text(ntfy.click_base_url)}
        placeholder="https://computer.tailnet.ts.net"
        onSave={(address) => {
          save({ click_base_url: optional(address) });
        }}
      />
      <WarningLine text={WARNING} />
    </div>
  );
}

export function NtfySection() {
  return (
    <SettingsSection title="ntfy" bare>
      <NtfyFields />
    </SettingsSection>
  );
}
