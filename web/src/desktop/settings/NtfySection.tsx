import { useState } from "react";
import { useStore } from "../../store/context.ts";
import { TextField } from "../ui/controls.tsx";
import { useSaveNtfy, type Ntfy } from "./ntfy.ts";
import { SettingsRow, SettingsSection, SwitchRow, WarningLine } from "./rows.tsx";

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

/**
 * The server, topic and link address, and the warning about public topics. With
 * `enablesWithTopic`, ntfy was turned on with no topic yet, which the daemon refuses: the
 * first topic turns it on with it.
 */
export function NtfyDetails({
  ntfy,
  save,
  enablesWithTopic = false,
}: {
  ntfy: Ntfy;
  save: (change: Partial<Ntfy>) => void;
  enablesWithTopic?: boolean;
}) {
  return (
    <>
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
        onSave={(typed) => {
          const topic = optional(typed);
          save(enablesWithTopic && topic !== null ? { topic, enabled: true } : { topic });
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
    </>
  );
}

/** ntfy's switch and fields, saved on the daemon as they change; a refused one goes back. */
export function NtfyFields() {
  const { state } = useStore();
  const save = useSaveNtfy();
  const rules = state.notifications;
  if (rules === null || save === null) return null;
  const { ntfy } = rules;
  return (
    <div className="dks-rows">
      <SwitchRow
        label="Send to ntfy"
        on={ntfy.enabled}
        onChange={(enabled) => {
          save({ enabled });
        }}
      />
      <NtfyDetails ntfy={ntfy} save={save} />
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
