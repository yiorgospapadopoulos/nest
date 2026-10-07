import { useId, useState } from "react";
import type { Connector } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import type { Tone } from "../../store/selectors.ts";
import { Pill } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";

const STATUS: Record<string, { tone: Tone; label: string }> = {
  connected: { tone: "rev", label: "Connected" },
  "needs-auth": { tone: "wait", label: "Needs sign-in" },
  failed: { tone: "fail", label: "Failed" },
  pending: { tone: "run", label: "Connecting" },
};

const HINTS: Record<Connector["manage_hint"], string> = {
  "claude.ai": "Sign in on claude.ai",
  claude_code: "Set up with /mcp in Claude Code",
};

/** MCP servers and claude.ai connectors with the status Claude Code last reported. */
export function ConnectorsCard() {
  const { state } = useStore();
  const all = state.connectors ?? [];
  const groups = [
    { title: "claude.ai connectors", items: all.filter((c) => c.group === "claude.ai") },
    { title: "Plugins and local servers", items: all.filter((c) => c.group !== "claude.ai") },
  ];
  return (
    <section aria-labelledby="connectors-title">
      <h2 className="pg-h" id="connectors-title">
        Connectors
      </h2>
      {state.connectors === null && <div className="lgrp gl pad note">Loading...</div>}
      {state.connectors?.length === 0 && (
        <div className="lgrp gl pad note">
          None reported yet. They appear after an agent runs in Claude Code.
        </div>
      )}
      {groups.map(
        ({ title, items }) => items.length > 0 && <Group key={title} title={title} items={items} />,
      )}
    </section>
  );
}

/** A disclosure, closed by default: the group's name, what needs the user and a count. */
function Group({ title, items }: { title: string; items: Connector[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const attention = items.filter((c) => c.status === "needs-auth" || c.status === "failed");
  const tone: Tone = attention.some((c) => c.status === "failed") ? "fail" : "wait";
  const count = attention.length;
  return (
    <div>
      <button
        id={`${id}-h`}
        className="pg-h pgb"
        aria-expanded={open}
        aria-controls={open ? `${id}-list` : undefined}
        onClick={() => {
          setOpen(!open);
        }}
      >
        <Icon name="chev" className="cv" />
        {title}
        {count > 0 && (
          <Pill
            tone={tone}
            label={`${String(count)} ${count === 1 ? "needs" : "need"} attention`}
          />
        )}
        <span className="gc">{items.length}</span>
      </button>
      {open && (
        <div id={`${id}-list`} className="lgrp gl" role="region" aria-labelledby={`${id}-h`}>
          {items.map((c) => (
            <ConnectorRow key={c.name} connector={c} />
          ))}
        </div>
      )}
    </div>
  );
}

function ConnectorRow({ connector: c }: { connector: Connector }) {
  const status = STATUS[c.status] ?? { tone: "done", label: c.status };
  return (
    <div className="srow">
      <span className="cn">
        <span className="cico" aria-hidden="true">
          {c.display_name.slice(0, 1).toUpperCase()}
        </span>
        <span>{c.display_name}</span>
      </span>
      <span className="cr2">
        <Pill tone={status.tone} label={status.label} />
        {c.status !== "connected" && (
          <span className="hint">{c.error ?? HINTS[c.manage_hint]}</span>
        )}
      </span>
    </div>
  );
}
