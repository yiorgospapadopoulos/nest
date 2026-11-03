import { useState } from "react";
import type { RepoConfig } from "../../../api/types.ts";
import { projectTabs, type ProjectTab } from "../catalog.ts";
import { ConfigurationTab } from "../project/ConfigurationTab.tsx";
import { GeneralTab } from "../project/GeneralTab.tsx";
import { ArtifactsTab, ChatsTab, LookTab, WorktreesTab } from "../project/ProjectTabs.tsx";
import { useProjectSaver } from "../project/useProjectSaver.ts";
import { SettingsTabs } from "../rows.tsx";

/** A project's settings in tabs (B81), as ProjectPage.swift; changes save as they are made. */
export function ProjectPage({ repo }: { repo: RepoConfig }) {
  const [chosen, setChosen] = useState<ProjectTab>("General");
  const save = useProjectSaver();
  const tabs = projectTabs(repo.git);
  const tab = tabs.includes(chosen) ? chosen : "General";
  return (
    <>
      <SettingsTabs
        label="Project settings"
        tabs={tabs.map((t) => [t, t] as const)}
        selection={tab}
        onSelect={setChosen}
      />
      {tab === "General" && <GeneralTab repo={repo} save={save} />}
      {tab === "Configuration" && <ConfigurationTab repo={repo} />}
      {tab === "Chats" && <ChatsTab repo={repo} save={save} />}
      {tab === "Worktrees" && <WorktreesTab repo={repo} save={save} />}
      {tab === "Look" && <LookTab repo={repo} save={save} />}
      {tab === "Artifacts" && <ArtifactsTab repo={repo} />}
    </>
  );
}
