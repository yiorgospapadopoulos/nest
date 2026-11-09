import { BLOCKED, KINDS, PERMISSIONS, useComputerPage } from "../../../screens/chat/useComputer.ts";
import { Toggle } from "../../ui/controls.tsx";
import { SettingsRow, SettingsSection, SwitchRow, Value } from "../rows.tsx";

/**
 * Computer use (B150): the master switch, the Mac's permissions as they really are, whether
 * pixies may use it, and the simulators and the shared browser.
 */
export function ComputerPage() {
  const { settings, status, save, ask } = useComputerPage();
  const disabled = settings === null;
  const onMac =
    status !== null && (status.accessibility !== null || status.screen_recording !== null);
  return (
    <>
      <SettingsSection>
        <SwitchRow
          label="Let chats use apps"
          on={settings?.enabled ?? false}
          disabled={disabled}
          onChange={(enabled) => {
            save({ enabled });
          }}
        />
      </SettingsSection>
      {onMac && (
        <SettingsSection title="Permissions">
          {PERMISSIONS.map(([name, label]) => (
            <PermissionRow
              key={name}
              label={label}
              granted={status[name]}
              onAsk={() => void ask(name)}
            />
          ))}
        </SettingsSection>
      )}
      <SettingsSection>
        <SwitchRow
          label="Pixies may use it"
          on={settings?.pixies ?? false}
          disabled={disabled}
          onChange={(pixies) => {
            save({ pixies });
          }}
        />
      </SettingsSection>
      {status !== null && (
        <SettingsSection title="Simulators and browser">
          {KINDS.map(({ kind, label, get }) => {
            const found = status.kinds.find((k) => k.kind === kind);
            if (found === undefined) return null;
            return (
              <SettingsRow key={kind} label={label}>
                {found.ready ? (
                  <span className="dks-cu-ok">Ready</span>
                ) : (
                  <>
                    <Value text={found.reason ?? "Not available"} />
                    {found.link !== null && (
                      <a className="dks-cu-link" href={found.link} target="_blank" rel="noreferrer">
                        {get}
                      </a>
                    )}
                  </>
                )}
              </SettingsRow>
            );
          })}
        </SettingsSection>
      )}
    </>
  );
}

/** A permission's switch as it really is; while blocked, a red line with Open. */
function PermissionRow({
  label,
  granted,
  onAsk,
}: {
  label: string;
  granted: boolean | null;
  onAsk: () => void;
}) {
  return (
    <SettingsRow
      label={
        <span className="dks-cu-lab">
          <span>{label}</span>
          {granted === false && (
            <span className="dks-cu-fail">
              {BLOCKED}
              <button type="button" aria-label={`Open ${label} in System Settings`} onClick={onAsk}>
                Open
              </button>
            </span>
          )}
        </span>
      }
    >
      <Toggle checked={granted === true} onChange={onAsk} label={label} />
    </SettingsRow>
  );
}
