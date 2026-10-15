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

// Where claude.ai connectors are signed in to.
export const CLAUDE_AI_CONNECTORS = "https://claude.ai/settings/connectors";
// Signs in to an MCP server on the Mac, where Claude Code can open the browser for it.
const SIGN_IN_COMMAND = "claude /mcp";

/** MCP servers and claude.ai connectors with the status Claude Code last reported. */
export function ConnectorsCard() {
  return (
    <section aria-labelledby="connectors-title">
      <h2 className="pg-h" id="connectors-title">
        Connectors
      </h2>
      <ConnectorGroups opened={false} />
    </section>
  );
}

/**
 * The connectors in their groups, closed by default on the Account tab; `opened` shows them
 * at once, as `/mcp` does (B59).
 */
export function ConnectorGroups({ opened }: { opened: boolean }) {
  const { state } = useStore();
  const all = state.connectors ?? [];
  const groups = [
    { title: "claude.ai connectors", items: all.filter((c) => c.group === "claude.ai") },
    { title: "Plugins and local servers", items: all.filter((c) => c.group !== "claude.ai") },
  ];
  return (
    <>
      {state.connectors === null && <div className="lgrp gl pad note">Loading...</div>}
      {state.connectors?.length === 0 && (
        <div className="lgrp gl pad note">
          None reported yet. They appear after an agent runs in Claude Code.
        </div>
      )}
      {groups.map(
        ({ title, items }) =>
          items.length > 0 && <Group key={title} title={title} items={items} opened={opened} />,
      )}
    </>
  );
}

interface GroupProps {
  title: string;
  items: Connector[];
  opened: boolean;
}

/** A disclosure: the group's name, what needs the user and a count. */
function Group({ title, items, opened }: GroupProps) {
  const [open, setOpen] = useState(opened);
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
  if (c.status === "needs-auth") return <SignInRow connector={c} />;
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

/**
 * A server that needs signing in to (B59): claude.ai connectors on claude.ai; others from
 * the Mac, where Claude Code's /mcp opens the browser for their sign-in.
 */
function SignInRow({ connector: c }: { connector: Connector }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard.writeText(SIGN_IN_COMMAND).then(
      () => {
        setCopied(true);
      },
      () => {
        setCopied(false);
      },
    );
  };
  return (
    <div className="srow col">
      <span className="crow1">
        <span className="cn">
          <span className="cico" aria-hidden="true">
            {c.display_name.slice(0, 1).toUpperCase()}
          </span>
          <span>{c.display_name}</span>
        </span>
        <Pill tone="wait" label="Needs sign-in" />
      </span>
      {c.manage_hint === "claude.ai" ? (
        <a className="csign" href={CLAUDE_AI_CONNECTORS} target="_blank" rel="noreferrer">
          Sign in on claude.ai
        </a>
      ) : (
        <span className="csign">
          <span>
            Sign in from the Mac: run <code>{SIGN_IN_COMMAND}</code> in Terminal
          </span>
          <button className="lnk2" onClick={copy}>
            {copied ? "Copied" : "Copy"}
          </button>
        </span>
      )}
    </div>
  );
}
