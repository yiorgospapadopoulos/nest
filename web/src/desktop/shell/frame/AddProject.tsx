import { useRef, useState, type ReactNode } from "react";
import type { JsonValue, RepoConfig } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { GENERAL } from "../../../store/general.ts";
import { Icon } from "../../../ui/Icon.tsx";
import { useApi, useBridge } from "../../context.ts";
import { Popover } from "../../ui/Popover.tsx";
import { ProjectMark } from "../bits.tsx";
import { useShell } from "../context.ts";
import { addProjectRows, folderChoice } from "./menus.ts";

/**
 * The strip's + and its popover, as the Mac's AddProjectPopover: General, the projects not
 * open with their folders, then Add folder…, which asks the system for a folder and opens
 * it as a project (registering it first when it is new).
 */
export function AddProjectButton() {
  const { state, actions } = useStore();
  const shell = useShell();
  const bridge = useBridge();
  const api = useApi();
  const button = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const { generalDetail, closed } = addProjectRows(shell.desk.tabs.open, state.repos);
  const close = () => {
    setOpen(false);
  };
  const choose = (name: string) => {
    close();
    shell.openProject(name);
  };
  const addFolder = async () => {
    close();
    let path: string | null;
    try {
      path = await bridge.pickFolder();
    } catch (error) {
      actions.toast(error instanceof Error ? error.message : "Could not open the folder dialog");
      return;
    }
    if (path === null) return;
    const choice = folderChoice(path, state.repos);
    if ("open" in choice) {
      shell.openProject(choice.open);
      return;
    }
    let repo: RepoConfig;
    try {
      repo = await api.registerRepo(choice.register);
    } catch (error) {
      actions.toast(error instanceof Error ? error.message : "Could not add the project", "error");
      return;
    }
    // Shown at once, as the daemon's own event will.
    actions.receive({
      id: null,
      ts: new Date().toISOString(),
      session_id: null,
      type: "repo.added",
      payload: { repo: repo as unknown as JsonValue },
    });
    shell.openProject(repo.name);
  };
  return (
    <>
      <button
        ref={button}
        className="dk-tadd"
        aria-label="Open another project"
        title="Open another project"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
      >
        <Icon name="plus" />
      </button>
      {open && (
        <Popover
          anchor={button}
          label="Open another project"
          align="start"
          className="fr-add"
          onClose={close}
        >
          <Row
            icon={<Icon name="chat" />}
            title="General"
            detail={generalDetail}
            onClick={() => {
              choose(GENERAL);
            }}
          />
          <hr />
          <h3>Open a project</h3>
          {closed.map((repo) => (
            <Row
              key={repo.name}
              icon={<ProjectMark name={repo.name} repo={repo} />}
              title={repo.name}
              detail={repo.path}
              path
              onClick={() => {
                choose(repo.name);
              }}
            />
          ))}
          {closed.length > 0 && <hr />}
          <Row icon={<Icon name="folder" />} title="Add folder…" onClick={() => void addFolder()} />
        </Popover>
      )}
    </>
  );
}

interface RowProps {
  icon: ReactNode;
  title: string;
  detail?: string;
  // A folder path, in the code font.
  path?: boolean;
  onClick: () => void;
}

function Row({ icon, title, detail, path = false, onClick }: RowProps) {
  return (
    <button className="fr-addrow" onClick={onClick}>
      <span className="fr-addi">{icon}</span>
      <span className="fr-addt">
        <span>{title}</span>
        {detail !== undefined && (
          <small className={path ? "path" : undefined} title={path ? detail : undefined}>
            {path ? middle(detail) : detail}
          </small>
        )}
      </span>
    </button>
  );
}

// About what fits the popover's 280 px in the code font.
const PATH_ROOM = 42;

/** A long path shortened in the middle, as the Mac truncates it. */
function middle(text: string): string {
  if (text.length <= PATH_ROOM) return text;
  const head = Math.floor((PATH_ROOM - 1) / 3);
  return `${text.slice(0, head)}…${text.slice(text.length - (PATH_ROOM - 1 - head))}`;
}
