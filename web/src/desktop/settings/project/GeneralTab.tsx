import { useEffect, useState } from "react";
import type { RepoConfig } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { useApi } from "../../context.ts";
import { Button } from "../../ui/controls.tsx";
import { SettingsRow, SettingsSection, Value } from "../rows.tsx";
import { Confirm } from "../../sheets/Alert.tsx";
import { shortPath, useSettingsChange } from "../config/util.ts";
import { TextAlert } from "./parts.tsx";
import { Dropdown } from "../rows.tsx";
import type { SaveProject } from "./useProjectSaver.ts";
import { removalConsequence } from "./worktree.ts";

/** A project's name, folder and kind, its git settings, and Remove (ProjectPage.swift). */
export function GeneralTab({ repo, save }: { repo: RepoConfig; save: SaveProject }) {
  const api = useApi();
  const { state, actions } = useStore();
  const change = useSettingsChange();
  const [removing, setRemoving] = useState(false);
  // Open and archived chats; the daemon deletes them with the project.
  const chats = Object.values(state.sessions)
    .filter((s) => s.repo === repo.name)
    .map((s) => s.id);
  return (
    <>
      <SettingsSection title="Project">
        <SettingsRow label="Name">
          <Value text={repo.name} />
        </SettingsRow>
        <SettingsRow label="Folder">
          <Value text={shortPath(repo.path)} mono />
          <Button
            onClick={() => {
              change("Could not open the folder", () => api.openRepo(repo.name, "finder"));
            }}
          >
            Show in Files
          </Button>
        </SettingsRow>
        <SettingsRow label="Kind">
          <Value text={repo.git ? "Git repository" : "Plain folder"} />
        </SettingsRow>
      </SettingsSection>
      {repo.git && <GitSection repo={repo} save={save} />}
      <SettingsSection title="Remove">
        <SettingsRow label={`Remove ${repo.name} from Nest`}>
          <Button
            kind="danger"
            onClick={() => {
              setRemoving(true);
            }}
          >
            Remove
          </Button>
        </SettingsRow>
      </SettingsSection>
      {removing && (
        <Confirm
          title={`Remove ${repo.name} from Nest?`}
          message={removalConsequence(chats.length)}
          action="Remove"
          destructive
          onConfirm={() => void actions.removeRepo(repo.name, chats)}
          onClose={() => {
            setRemoving(false);
          }}
        />
      )}
    </>
  );
}

function GitSection({ repo, save }: { repo: RepoConfig; save: SaveProject }) {
  const { actions } = useStore();
  const [branches, setBranches] = useState<string[]>([]);
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    let live = true;
    void actions.branches(repo.name).then((found) => {
      if (live && found !== null) setBranches(found);
    });
    return () => {
      live = false;
    };
  }, [actions, repo.name]);
  const url = repo.remote_url;
  return (
    <SettingsSection title="Git">
      <SettingsRow label="Default branch">
        <Dropdown
          label="Default branch"
          title={repo.default_branch ?? "-"}
          width={140}
          disabled={branches.length === 0}
          items={() =>
            branches.map((branch) => ({
              title: branch,
              checked: branch === repo.default_branch,
              onSelect: () => {
                if (branch !== repo.default_branch) {
                  save(repo.name, () => ({ default_branch: branch }));
                }
              },
            }))
          }
        />
      </SettingsRow>
      <SettingsRow label="Push to">
        {url === null ? <span className="dkp-none">No remote yet</span> : <Value text={url} mono />}
        <Button
          onClick={() => {
            setEditing(true);
          }}
        >
          {url === null ? "Set remote" : "Change"}
        </Button>
      </SettingsRow>
      {editing && (
        <TextAlert
          title={url === null ? "Set the push address" : "Change the push address"}
          message={`Nest pushes ${repo.name} only to this address.`}
          placeholder="git@github.com:you/repo.git"
          initial={url ?? ""}
          onSave={(text) => {
            const typed = text.trim();
            if (typed !== "") {
              save(repo.name, () => ({ remote_url: typed }), "Could not save the push address");
            }
          }}
          onClose={() => {
            setEditing(false);
          }}
        />
      )}
    </SettingsSection>
  );
}
