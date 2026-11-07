import { useEffect } from "react";
import type { RepoConfig } from "../../../api/types.ts";
import { NEW_SERVER, PROJECT_INTRO } from "../../../screens/settings/configText.ts";
import { useStore } from "../../../store/context.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Button } from "../../ui/controls.tsx";
import { ConfigModalsProvider } from "../config/ConfigModals.tsx";
import { useConfigModals } from "../config/modals.ts";
import {
  ConfigChip,
  ConfigIcon,
  ConfigLabel,
  ConfigRow,
  ConfigSubRow,
  RowText,
} from "../config/parts.tsx";
import { fileName, useOpenPath } from "../config/util.ts";

/**
 * The project's own instructions files, skills and `.mcp.json` servers, which only Claude
 * reads, as ProjectPage.swift's ProjectConfigurationTab, with Configuration's editor and
 * forms over it.
 */
export function ConfigurationTab({ repo }: { repo: RepoConfig }) {
  return (
    <ConfigModalsProvider>
      <ProjectConfiguration repo={repo} />
    </ConfigModalsProvider>
  );
}

function ProjectConfiguration({ repo }: { repo: RepoConfig }) {
  const { state, actions } = useStore();
  const modals = useConfigModals();
  const config = state.settings.projectConfiguration[repo.name];
  useEffect(() => {
    void actions.loadProjectConfiguration(repo.name);
  }, [actions, repo.name]);
  const skills = `${repo.path}/.claude/skills`;
  const openPath = useOpenPath();
  return (
    <div className="dkc-page">
      <p className="dkc-intro">{PROJECT_INTRO}</p>
      {config === undefined ? (
        <div className="dkc-loading">
          <Fireflies />
        </div>
      ) : (
        <>
          <ConfigLabel text="Instructions" />
          {config.instructions.map((file) => {
            const name = fileName(file.path);
            return (
              <ConfigRow key={file.path}>
                <ConfigIcon name="doc" />
                <RowText title={<span className="mono">{name}</span>}>
                  {file.exists
                    ? name === "CLAUDE.md"
                      ? "Read by Claude"
                      : "Read by Codex; Claude reads it when CLAUDE.md imports it"
                    : "Not made yet"}
                </RowText>
                <Button
                  onClick={() => {
                    modals.edit({ path: file.path, title: name, note: repo.name });
                  }}
                >
                  {file.exists ? "Edit" : "Create"}
                </Button>
              </ConfigRow>
            );
          })}
          <ConfigLabel text="Skills" />
          <ConfigRow>
            <ConfigIcon name="star" />
            <RowText title="Project skills">.claude/skills · Claude only</RowText>
            <Button
              onClick={() => {
                modals.form({ skill: { repo: repo.name, folder: skills } });
              }}
            >
              New skill
            </Button>
            {openPath !== null && (
              <Button
                onClick={() => {
                  openPath(skills, false, true);
                }}
              >
                Open folder
              </Button>
            )}
          </ConfigRow>
          {config.skills.map((skill) => (
            <ConfigSubRow key={skill.path}>
              <b className="dkc-name">{skill.name}</b>
              <span className="dkc-fill dkc-dim">{skill.description ?? ""}</span>
              <Button
                onClick={() => {
                  modals.edit({ path: skill.path, title: skill.name, note: "project skill" });
                }}
              >
                Edit
              </Button>
            </ConfigSubRow>
          ))}
          <ConfigLabel text="MCP servers" />
          <ConfigRow>
            <ConfigIcon name="server" />
            <RowText title="Project servers">.mcp.json · Claude only</RowText>
            <Button
              onClick={() => {
                modals.form({ server: NEW_SERVER, isNew: true, repo: repo.name });
              }}
            >
              Add server
            </Button>
            <Button
              onClick={() => {
                modals.edit({
                  path: `${repo.path}/.mcp.json`,
                  title: "MCP servers",
                  note: repo.name,
                });
              }}
            >
              Edit .mcp.json
            </Button>
          </ConfigRow>
          {config.mcp_servers.map((server) => (
            <ConfigSubRow key={server.name}>
              <b className="dkc-name">{server.name}</b>
              <span className="dkc-fill dkc-dim mono">{server.summary}</span>
              <ConfigChip text="Claude only" />
              <Button
                kind="danger"
                onClick={() => void actions.deleteProjectMcpServer(repo.name, server.name)}
              >
                Remove
              </Button>
            </ConfigSubRow>
          ))}
        </>
      )}
    </div>
  );
}
