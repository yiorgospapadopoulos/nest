import { useId } from "react";
import { BLOCKED, KINDS, PERMISSIONS, useComputerPage } from "../chat/useComputer.ts";
import { Section, Status, SwitchRow } from "./rows.tsx";

/**
 * Computer use (B150), as on the Mac: the master switch, the Mac's permissions as they really
 * are, whether pixies may use it, and the simulators and browser.
 */
export function ComputerPage() {
  const { settings, status, save, ask } = useComputerPage();
  const disabled = settings === null;
  const onMac =
    status !== null && (status.accessibility !== null || status.screen_recording !== null);
  return (
    <>
      <Section>
        <SwitchRow
          label="Let chats use apps"
          on={settings?.enabled ?? false}
          disabled={disabled}
          onToggle={() => {
            if (settings !== null) save({ enabled: !settings.enabled });
          }}
        />
      </Section>
      {onMac && (
        <Section title="Permissions">
          {PERMISSIONS.map(([name, label]) => (
            <PermissionRow
              key={name}
              label={label}
              granted={status[name]}
              onAsk={() => void ask(name)}
            />
          ))}
        </Section>
      )}
      <Section>
        <SwitchRow
          label="Pixies may use it"
          on={settings?.pixies ?? false}
          disabled={disabled}
          onToggle={() => {
            if (settings !== null) save({ pixies: !settings.pixies });
          }}
        />
      </Section>
      {status !== null && (
        <Section title="Simulators and browser">
          {KINDS.map(({ kind, label, get }) => {
            const found = status.kinds.find((k) => k.kind === kind);
            if (found === undefined) return null;
            return (
              <div key={kind} className="srow">
                <span className="slab">
                  {label}
                  {!found.ready && found.link !== null && (
                    <a className="cu-get" href={found.link} target="_blank" rel="noreferrer">
                      {get}
                    </a>
                  )}
                </span>
                {found.ready ? (
                  <Status tone="ok" label="Ready" />
                ) : (
                  <span className="hint">{found.reason ?? "Not available"}</span>
                )}
              </div>
            );
          })}
        </Section>
      )}
    </>
  );
}

/** A permission's switch as it really is; while blocked, a red line with Open on Mac. */
function PermissionRow({
  label,
  granted,
  onAsk,
}: {
  label: string;
  granted: boolean | null;
  onAsk: () => void;
}) {
  const id = useId();
  return (
    <div className="srow">
      <span className="slab">
        <span id={id}>{label}</span>
        {granted === false && (
          <span className="cu-fail">
            {BLOCKED}
            <button onClick={onAsk}>Open on Mac</button>
          </span>
        )}
      </span>
      <button
        className="sw"
        role="switch"
        aria-checked={granted === true}
        aria-labelledby={id}
        onClick={onAsk}
      />
    </div>
  );
}
