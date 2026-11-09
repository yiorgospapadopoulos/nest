import { Loading, Row, Section, SelectRow, SwitchRow } from "./rows.tsx";
import { ACCESS_CHOICES, FIRST_ACCESS, commandLine, useTerminalAgents } from "./terminalAgents.ts";

/**
 * Terminal agents (B151), as on the Mac: Claude Code, Codex, other AI apps and the `nest`
 * command, each switched on with its own level of access to Nest's chats.
 */
export function TerminalAgentsPage() {
  const { clients, busy, set } = useTerminalAgents();
  if (clients === null) return <Loading />;
  return (
    <>
      {clients.map((client) => {
        const line = client.on ? commandLine(client) : null;
        return (
          <Section key={client.kind}>
            <SwitchRow
              label={client.label}
              on={client.on}
              disabled={busy === client.kind}
              onToggle={() => void set(client.kind, client.on ? null : FIRST_ACCESS)}
            />
            {client.on && client.access !== null && (
              <SelectRow
                label="Access"
                value={client.access}
                choices={ACCESS_CHOICES}
                disabled={busy === client.kind}
                onChange={(access) => void set(client.kind, access)}
              />
            )}
            {line !== null && (
              <Row label={client.kind === "shell" ? "Command" : "Run"}>
                <code className="hint">{line}</code>
              </Row>
            )}
          </Section>
        );
      })}
    </>
  );
}
