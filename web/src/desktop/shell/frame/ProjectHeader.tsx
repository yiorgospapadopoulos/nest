import type { CSSProperties } from "react";
import { useStore } from "../../../store/context.ts";
import { GENERAL, projectName } from "../../../store/general.ts";
import { draftKey } from "../../../store/state.ts";
import { Icon } from "../../../ui/Icon.tsx";
import type { LoadedMap } from "../../chat/branchMaps.ts";
import { keysText as keysOf } from "../../layout/shortcuts.ts";
import { terminalPane } from "../../layout/tools.ts";
import { Menu } from "../../ui/Menu.tsx";
import { ProjectMark, ForkIcon } from "../bits.tsx";
import { useShell } from "../context.ts";
import { BranchMapPanel } from "./BranchMapPanel.tsx";
import { middleName } from "./branchLanes.ts";
import { GIT_INIT } from "./gitInit.ts";
import { projectMenu } from "./menus.ts";
import { useBranchMapOpen, useFreshWhenOpen } from "./projectMap.ts";

// About what fits the chip's 102 pixels.
const CHIP_NAME = 10;

/**
 * The top of the sidebar, as the Mac's ProjectHeader: the project's icon and name opening
 * its menu, where new chats start (or Init for a plain folder) opening the branch map,
 * marked Live while the map follows changes. The name comes from the selected place and
 * never from anything an open chat reads, so open chats do not look as if they moved.
 */
export function ProjectHeader({ map }: { map: LoadedMap | null }) {
  const { state } = useStore();
  const shell = useShell();
  const { repo } = shell;
  const [open, toggle] = useBranchMapOpen(repo.name);
  useFreshWhenOpen(repo.name, repo.git, open);
  const branch =
    repo.selected_place?.branch ??
    repo.current_branch ??
    (map?.map.detached === true ? "detached" : repo.default_branch);
  const general = repo.name === GENERAL;
  const live = open && map !== null && !state.reconnecting;
  return (
    <>
      <div className="fr-phead">
        <ProjectMenu />
        {!general && repo.git && branch !== null && (
          <BranchLabel
            branch={branch}
            selected={repo.selected_place !== null}
            open={open}
            color={map?.color(branch) ?? null}
            onToggle={toggle}
          />
        )}
        {!general && !repo.git && <InitButton />}
        <span className="grow" />
        {live && (
          <span className="fr-live" title="The branch map updates as branches and worktrees change">
            <i />
            <span>Live</span>
          </span>
        )}
      </div>
      {open && repo.git && map !== null && <BranchMapPanel key={repo.name} map={map} />}
    </>
  );
}

function ProjectMenu() {
  const { actions } = useStore();
  const shell = useShell();
  const { repo } = shell;
  return (
    <Menu
      label={`Project ${projectName(repo.name)}`}
      items={() =>
        projectMenu(repo.name, shell.editors, keysOf("openInEditor"), {
          // Always one more terminal, as the Mac's newTerminal.
          newTerminal: () => {
            shell.update((s) => {
              s.openTool(terminalPane(repo.path), shell.workspaceSize());
            });
          },
          newBrowser: () => {
            shell.newBrowser();
          },
          openIn: shell.openIn,
          copyPath: () => {
            navigator.clipboard.writeText(repo.path).then(
              () => {
                actions.toast(`Copied ${repo.path}`);
              },
              () => {
                actions.toast("Could not copy", "error");
              },
            );
          },
          settings: () => {
            shell.openSettings({ project: repo.name });
          },
        })
      }
    >
      {(trigger) => (
        <button {...trigger} className="fr-pmenu" aria-label={`Project ${projectName(repo.name)}`}>
          <ProjectMark name={repo.name} repo={repo} size={15} />
          <span className="fr-pname">{projectName(repo.name)}</span>
          <Icon name="chev" className="fr-pchev" />
        </button>
      )}
    </Menu>
  );
}

function BranchLabel({
  branch,
  selected,
  open,
  color,
  onToggle,
}: {
  branch: string;
  selected: boolean;
  open: boolean;
  color: string | null;
  onToggle: () => void;
}) {
  return (
    <button
      className={`fr-pbranch${open ? " on" : ""}${selected ? " picked" : ""}`}
      style={selected && color !== null ? ({ "--lane": color } as CSSProperties) : undefined}
      title={branch}
      aria-label={`Branch ${branch}, ${open ? "hide" : "show"} branch map`}
      aria-expanded={open}
      onClick={onToggle}
    >
      <ForkIcon />
      <span>{selected ? middleName(branch, CHIP_NAME) : branch}</span>
      <Icon name="chev" className="fr-pbchev" />
    </button>
  );
}

/** A plain folder's place for the branch: a new chat that sets it up with git. */
function InitButton() {
  const { actions } = useStore();
  const shell = useShell();
  return (
    <button
      className="fr-init"
      title="Set this folder up as a git repository"
      aria-label="Init: set this folder up as a git repository"
      onClick={() => {
        actions.setDraftText(draftKey({ repo: shell.repo.name }), GIT_INIT);
        shell.newChat();
      }}
    >
      <ForkIcon />
      Init
    </button>
  );
}
