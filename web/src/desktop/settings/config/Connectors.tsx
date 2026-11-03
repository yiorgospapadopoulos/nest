import { useEffect, useState } from "react";
import type { Connector } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { useBridge } from "../../context.ts";
import { Button } from "../../ui/controls.tsx";
import { FoldChevron, StatusLabel, type StatusTone } from "./parts.tsx";

// The MCP servers and claude.ai connectors Claude Code reported, grouped, with their
// status and where to set them up (B59), as ConnectorsList.swift.

const CLAUDE_AI_SETTINGS = "https://claude.ai/settings/connectors";

type Group = "claudeAI" | "claudeCode";
const GROUPS: { kind: Group; title: string }[] = [
  { kind: "claudeAI", title: "claude.ai connectors" },
  { kind: "claudeCode", title: "Plugins and local servers" },
];

const STATES: Record<string, { tone: StatusTone; label: string }> = {
  connected: { tone: "review", label: "Connected" },
  "needs-auth": { tone: "waiting", label: "Needs sign-in" },
  needs_auth: { tone: "waiting", label: "Needs sign-in" },
  failed: { tone: "failed", label: "Failed" },
  pending: { tone: "running", label: "Connecting" },
};

function stateOf(connector: Connector): { tone: StatusTone; label: string } {
  const status = connector.status;
  return (
    STATES[status] ?? { tone: "done", label: status.charAt(0).toUpperCase() + status.slice(1) }
  );
}

const needsSignIn = (c: Connector) => c.status === "needs-auth" || c.status === "needs_auth";
const managedOnClaudeAI = (c: Connector) =>
  c.group === "claude.ai" || c.manage_hint === "claude.ai";

/** "1 needs sign-in, 2 failed"; null when nothing needs sign-in or failed. */
function attention(connectors: Connector[]): string | null {
  const signIns = connectors.filter(needsSignIn).length;
  const failures = connectors.filter((c) => c.status === "failed").length;
  const parts = [
    signIns > 0 ? `${String(signIns)} ${signIns === 1 ? "needs" : "need"} sign-in` : null,
    failures > 0 ? `${String(failures)} failed` : null,
  ].filter((p) => p !== null);
  return parts.length === 0 ? null : parts.join(", ");
}

export function ConnectorsList() {
  const { state, actions } = useStore();
  const [open, setOpen] = useState<Group[]>([]);
  useEffect(() => {
    void actions.loadConnectors();
  }, [actions]);
  const all = state.connectors ?? [];
  const sections = GROUPS.map((group) => ({
    ...group,
    connectors: all.filter((c) => (c.group === "claude.ai") === (group.kind === "claudeAI")),
  })).filter((section) => section.connectors.length > 0);
  return (
    <div className="dkc-conns">
      {sections.length === 0 && (
        <p className="dkc-conn-none">
          Claude Code has not reported any yet. They appear after an agent&apos;s first turn.
        </p>
      )}
      {sections.map((section) => {
        const shown = open.includes(section.kind);
        const warn = attention(section.connectors);
        return (
          <div key={section.kind}>
            <button
              type="button"
              className="dkc-conn-h"
              aria-expanded={shown}
              onClick={() => {
                setOpen(shown ? open.filter((k) => k !== section.kind) : [...open, section.kind]);
              }}
            >
              <FoldChevron open={shown} />
              {section.title}
              <span className="num">{section.connectors.length}</span>
              {warn !== null && <StatusLabel tone="waiting" label={warn} />}
            </button>
            {shown &&
              section.connectors.map((connector) => (
                <ConnectorRow key={connector.name} connector={connector} />
              ))}
          </div>
        );
      })}
    </div>
  );
}

function ConnectorRow({ connector }: { connector: Connector }) {
  const bridge = useBridge();
  const [hint, setHint] = useState(false);
  const status = stateOf(connector);
  const claudeAI = managedOnClaudeAI(connector);
  const name = connector.display_name;
  // A server's sign-in runs claude /mcp in a terminal, which this app cannot start itself:
  // it says where to set it up, as Set up in Claude Code does.
  const act = () => {
    if (claudeAI) void bridge.openExternal(CLAUDE_AI_SETTINGS);
    else setHint(!hint);
  };
  return (
    <div className="dkc-conn">
      <div className="dkc-conn-r">
        <span className="dkc-conn-i" aria-hidden="true">
          {name.slice(0, 1).toUpperCase()}
        </span>
        <span className="dkc-text">
          <span className="dkc-conn-n">{name}</span>
          {connector.status === "failed" && connector.error !== null && (
            <span className="dkc-conn-e">{connector.error}</span>
          )}
        </span>
        <StatusLabel tone={status.tone} label={status.label} />
        {needsSignIn(connector) ? (
          <Button
            kind="link"
            aria-label={`Sign in to ${name}`}
            title={claudeAI ? "Opens claude.ai's connector settings" : undefined}
            onClick={act}
          >
            Sign in
          </Button>
        ) : (
          connector.status !== "connected" && (
            <Button kind="link" onClick={act}>
              {claudeAI ? "Sign in on claude.ai" : "Set up in Claude Code"}
            </Button>
          )
        )}
      </div>
      {hint && (
        <p className="dkc-conn-hint">
          Run /mcp in Claude Code to set up {name}; Nest picks it up on the next turn.
        </p>
      )}
    </div>
  );
}
