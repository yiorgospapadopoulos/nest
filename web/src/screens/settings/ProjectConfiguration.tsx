import { useEffect, useState } from "react";
import type { RepoConfig } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { ConfigEditor, type EditTarget } from "./ConfigEditor.tsx";
import { ServerFormSheet, SkillFormSheet } from "./ConfigForms.tsx";
import { fileName, NEW_SERVER, PROJECT_INTRO } from "./configText.ts";
import { Loading, Row, Section } from "./rows.tsx";

type Form = "server" | "skill";

/** What reads an instructions file of the project. */
function readBy(name: string, exists: boolean): string {
  if (!exists) return "Not made yet";
  return name === "CLAUDE.md"
    ? "Read by Claude"
    : "Read by Codex; Claude reads it when CLAUDE.md imports it";
}

/**
 * A project's own instructions files, skills and `.mcp.json` servers (B97, B102 item 31),
 * which only Claude reads, on top of the shared ones in Configuration.
 */
export function ProjectConfiguration({ repo }: { repo: RepoConfig }) {
  const { state, actions } = useStore();
  const config = state.settings.projectConfiguration[repo.name] ?? null;
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const [form, setForm] = useState<Form | null>(null);

  useEffect(() => {
    void actions.loadProjectConfiguration(repo.name);
  }, [actions, repo.name]);

  const close = () => {
    setForm(null);
  };
  return (
    <>
      <p className="cfg-intro">{PROJECT_INTRO}</p>
      {config === null ? (
        <Loading />
      ) : (
        <>
          <Section title="Instructions">
            {config.instructions.map((file) => {
              const name = fileName(file.path);
              return (
                <Row
                  key={file.path}
                  label={
                    <>
                      <span className="mono">{name}</span>
                      <span className="hint">{readBy(name, file.exists)}</span>
                    </>
                  }
                >
                  <button
                    className="b"
                    aria-label={`${file.exists ? "Edit" : "Create"} ${name}`}
                    onClick={() => {
                      setEditing({ path: file.path, title: name, note: repo.name });
                    }}
                  >
                    {file.exists ? "Edit" : "Create"}
                  </button>
                </Row>
              );
            })}
          </Section>
          <Section title="Skills">
            <Row
              label={
                <>
                  <span>Project skills</span>
                  <span className="hint">.claude/skills · Claude only</span>
                </>
              }
            >
              <button
                className="b"
                onClick={() => {
                  setForm("skill");
                }}
              >
                New skill
              </button>
            </Row>
            {config.skills.length === 0 && (
              <div className="srow note sub">No project skills yet</div>
            )}
            {config.skills.map((skill) => (
              <div key={skill.path} className="srow item sub">
                <span className="slab">
                  {skill.name}
                  {skill.description !== null && <span className="hint">{skill.description}</span>}
                </span>
                <button
                  className="b"
                  aria-label={`Edit ${skill.name}`}
                  onClick={() => {
                    setEditing({ path: skill.path, title: skill.name, note: "project skill" });
                  }}
                >
                  Edit
                </button>
              </div>
            ))}
          </Section>
          <Section title="MCP servers">
            <Row
              label={
                <>
                  <span>Project servers</span>
                  <span className="hint">.mcp.json · Claude only</span>
                </>
              }
            >
              <button
                className="b"
                onClick={() => {
                  setForm("server");
                }}
              >
                Add server
              </button>
              <button
                className="b"
                onClick={() => {
                  setEditing({
                    path: `${repo.path}/.mcp.json`,
                    title: "MCP servers",
                    note: repo.name,
                  });
                }}
              >
                Edit .mcp.json
              </button>
            </Row>
            {config.mcp_servers.length === 0 && (
              <div className="srow note sub">No project servers yet</div>
            )}
            {config.mcp_servers.map((server) => (
              <div key={server.name} className="srow item sub">
                <span className="slab">
                  {server.name}
                  <span className="hint mono">{server.summary}</span>
                </span>
                <button
                  className="b"
                  aria-label={`Remove ${server.name}`}
                  onClick={() => void actions.deleteProjectMcpServer(repo.name, server.name)}
                >
                  Remove
                </button>
              </div>
            ))}
          </Section>
        </>
      )}
      {editing !== null && (
        <ConfigEditor
          target={editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
      {form === "server" && (
        <ServerFormSheet initial={NEW_SERVER} isNew repo={repo.name} onClose={close} />
      )}
      {form === "skill" && (
        <SkillFormSheet
          repo={repo.name}
          onClose={close}
          onCreated={(name) => {
            close();
            setEditing({
              path: `${repo.path}/.claude/skills/${name}/SKILL.md`,
              title: name,
              note: "project skill",
            });
          }}
        />
      )}
    </>
  );
}
