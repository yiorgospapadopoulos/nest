import { useState } from "react";
import type { ClaudeCodeInfo } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Confirm } from "../pixies/Confirm.tsx";
import { ConnectorGroups } from "./ConnectorsCard.tsx";
import { Loading, Row, Section } from "./rows.tsx";
import { SkillsTab } from "./SkillsTab.tsx";

const TABS = ["Skills and plugins", "Connections"] as const;
type Tab = (typeof TABS)[number];

/** Claude Code on the Mac, its skills and plugins, and the connections (B81). */
export function ExtensionsPage() {
  const { state } = useStore();
  const [tab, setTab] = useState<Tab>("Skills and plugins");
  const info = state.settings.claudeCode;
  return (
    <>
      {info === null ? <Loading title="Claude Code" /> : <ClaudeCode info={info} />}
      <div className="ptabs" role="group" aria-label="Extensions">
        {TABS.map((t) => (
          <button
            key={t}
            aria-pressed={tab === t}
            onClick={() => {
              setTab(t);
            }}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "Connections" ? <ConnectorGroups opened={false} /> : <SkillsTab />}
    </>
  );
}

function ClaudeCode({ info }: { info: ClaudeCodeInfo }) {
  const { state, actions } = useStore();
  const [asking, setAsking] = useState(false);
  const install = state.settings.install;
  const running = install?.state === "running";
  return (
    <Section title="Claude Code">
      {info.installed ? (
        <>
          <Row label="Installed">
            <span className="sval">{info.version ?? "Unknown version"}</span>
          </Row>
          {info.path !== null && (
            <Row label="Path">
              <span className="sval mono">{info.path}</span>
            </Row>
          )}
        </>
      ) : (
        <Row label="Not installed">
          <button
            className="b b-pri"
            disabled={running}
            onClick={() => {
              setAsking(true);
            }}
          >
            {running ? "Installing..." : "Install Claude Code"}
          </button>
        </Row>
      )}
      <Row label="Agents use">
        <span className="sval">{info.bundled_version}</span>
      </Row>
      {install?.message != null && (
        <p className="srow note" role={install.state === "failed" ? "alert" : "status"}>
          {install.message}
        </p>
      )}
      {asking && (
        <Confirm
          title="Install Claude Code?"
          about="Nest runs Anthropic's official installer on your Mac."
          action="Install"
          onConfirm={() => void actions.installClaudeCode()}
          onClose={() => {
            setAsking(false);
          }}
        />
      )}
    </Section>
  );
}
