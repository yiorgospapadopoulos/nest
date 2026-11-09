import type { MenuEntry } from "../../ui/menuItems.ts";
import { Toggle } from "../../ui/controls.tsx";
import {
  ACCESS_CHOICES,
  FIRST_ACCESS,
  accessLabel,
  commandLine,
  useTerminalAgents,
} from "../../../screens/settings/terminalAgents.ts";
import { Dropdown, Note, SettingsRow, SettingsSection, Value } from "../rows.tsx";

/**
 * Terminal agents (B151): Claude Code, Codex, other AI apps and the `nest` command, each
 * switched on with its own level of access to Nest's chats.
 */
export function TerminalAgentsPage() {
  const { clients, busy, set } = useTerminalAgents();
  if (clients === null) {
    return (
      <SettingsSection>
        <Note>Loading</Note>
      </SettingsSection>
    );
  }
  return (
    <>
      {clients.map((client) => {
        const line = client.on ? commandLine(client) : null;
        const items = (): MenuEntry[] => [
          { type: "section", title: "Access" },
          ...ACCESS_CHOICES.map((choice) => ({
            title: choice.label,
            checked: choice.value === client.access,
            onSelect: () => void set(client.kind, choice.value),
          })),
        ];
        return (
          <SettingsSection key={client.kind}>
            <SettingsRow label={client.label}>
              {client.on && (
                <Dropdown
                  label={`${client.label} access`}
                  title={accessLabel(client.access)}
                  items={items}
                  disabled={busy === client.kind}
                />
              )}
              <Toggle
                checked={client.on}
                label={client.label}
                disabled={busy === client.kind}
                onChange={(on) => void set(client.kind, on ? FIRST_ACCESS : null)}
              />
            </SettingsRow>
            {line !== null && (
              <SettingsRow label={client.kind === "shell" ? "Command" : "Run"}>
                <Value text={line} mono />
              </SettingsRow>
            )}
          </SettingsSection>
        );
      })}
    </>
  );
}
