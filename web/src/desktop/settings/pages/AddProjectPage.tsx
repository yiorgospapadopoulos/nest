import { useState } from "react";
import { useStore } from "../../../store/context.ts";
import { useApi, useBridge } from "../../context.ts";
import { folderChoice } from "../../shell/frame/menus.ts";
import { useShell } from "../../shell/context.ts";
import { Button, TextField } from "../../ui/controls.tsx";
import { SettingsRow, SettingsSection } from "../rows.tsx";
import "../parts3/parts3.css";

/**
 * A folder typed or chosen in the system's folder dialog, then Add, as the Mac's
 * AddProjectPage: a folder already added opens its project; a new one is added and its
 * Settings page opens.
 */
export function AddProjectPage() {
  const { state, actions } = useStore();
  const api = useApi();
  const bridge = useBridge();
  const shell = useShell();
  // The daemon reads a leading ~ as this computer's home.
  const [path, setPath] = useState("~/");
  const [adding, setAdding] = useState(false);
  const empty = path.trim() === "";

  const choose = async () => {
    const chosen = await bridge.pickFolder();
    if (chosen !== null) setPath(chosen);
  };

  const add = async () => {
    const text = path.trim();
    if (text === "" || adding) return;
    const choice = folderChoice(text, state.repos);
    if ("open" in choice) {
      shell.openProject(choice.open);
      shell.openSettings({ project: choice.open });
      return;
    }
    setAdding(true);
    try {
      const added = await api.registerRepo(choice.register);
      await actions.refreshRepo(added.name);
      shell.openSettings({ project: added.name });
    } catch (error) {
      const reason = error instanceof Error ? error.message : "Something went wrong";
      actions.toast(`Could not add the project: ${reason}`, "error");
    } finally {
      setAdding(false);
    }
  };

  return (
    <SettingsSection>
      <SettingsRow label="Folder">
        <TextField
          label="Folder"
          placeholder="Folder"
          mono
          className="dks3-folder"
          value={path}
          onChange={setPath}
          onKeyDown={(event) => {
            if (event.key === "Enter") void add();
          }}
        />
        {bridge.native && <Button onClick={() => void choose()}>Choose…</Button>}
        <Button kind="primary" disabled={empty || adding} onClick={() => void add()}>
          Add
        </Button>
      </SettingsRow>
    </SettingsSection>
  );
}
