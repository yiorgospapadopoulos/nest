import { useState, type CSSProperties } from "react";
import { useStore } from "../../../store/context.ts";
import { GENERAL, projectName } from "../../../store/general.ts";
import { chatStatus, pendingFor } from "../../../store/selectors.ts";
import { draftKey } from "../../../store/state.ts";
import { Icon } from "../../../ui/Icon.tsx";
import type { LoadedMap } from "../../chat/branchMaps.ts";
import { branchChoice } from "../../chat/placePicker.ts";
import { keysText as keysOf } from "../../layout/shortcuts.ts";
import { terminalPane } from "../../layout/tools.ts";
import { Menu } from "../../ui/Menu.tsx";
import { ProjectMark, ForkIcon } from "../bits.tsx";
import { useShell } from "../context.ts";
import {
  branchChats,
  branchLanes,
  LANE_ROW,
  laneX,
  rowAction,
  type BranchChat,
  type LaneRow,
} from "./branchLanes.ts";
import { setNextDraftChoice } from "./draftChoice.ts";
import { useBranchMapOpen } from "./projectMap.ts";
import { GIT_INIT } from "./gitInit.ts";
import { projectMenu } from "./menus.ts";

// At most this many branch rows show; the rest scroll.
const VISIBLE_ROWS = 6;

/**
 * The top of the sidebar, as the Mac's ProjectHeader: the project's icon and name opening
 * its menu, its current branch (or Init for a plain folder) opening the branch map, marked
 * Live while the map follows changes.
 */
export function ProjectHeader({ map }: { map: LoadedMap | null }) {
  const { state } = useStore();
  const shell = useShell();
  const { repo } = shell;
  const [open, toggle] = useBranchMapOpen(repo.name);
  const branch = repo.current_branch ?? repo.default_branch;
  const general = repo.name === GENERAL;
  const live = open && map !== null && !state.reconnecting;
  return (
    <>
      <div className="fr-phead">
        <ProjectMenu />
        {!general && repo.git && branch !== null && (
          <BranchLabel
            branch={branch}
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
      {open && repo.git && map !== null && <BranchMapPanel map={map} />}
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
        projectMenu(repo.name, keysOf("openInVSCode"), {
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
  open,
  color,
  onToggle,
}: {
  branch: string;
  open: boolean;
  color: string | null;
  onToggle: () => void;
}) {
  return (
    <button
      className={open ? "fr-pbranch on" : "fr-pbranch"}
      style={open && color !== null ? ({ "--lane": color } as CSSProperties) : undefined}
      title={open ? "Hide the branch map" : "Show the branch map"}
      aria-label={`Branch ${branch}, ${open ? "hide" : "show"} branch map`}
      aria-expanded={open}
      onClick={onToggle}
    >
      <ForkIcon />
      <span>{branch}</span>
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

/**
 * The project's branches and worktrees as coloured lanes (B96, A7): each branch joined to
 * the branch it comes from; where the project folder is pulses. A click on a row starts a
 * new chat there (A8).
 */
function BranchMapPanel({ map }: { map: LoadedMap }) {
  const { state } = useStore();
  const shell = useShell();
  const lanes = branchLanes(map.map);
  const repo = shell.repo;
  const sessions = Object.values(state.sessions).filter(
    (s) => s.repo === repo.name && s.pixie_id == null,
  );
  const chats = branchChats(
    map.map,
    sessions,
    Object.values(state.claudeChats).filter((c) => c.repo === repo.name),
    repo,
    (s) => chatStatus(s, pendingFor(state, s.id)).tone,
  );
  return (
    <section className="fr-bmap" aria-label="Branch map">
      <header>
        <span>Branches and worktrees</span>
        <small>{lanes.count}</small>
      </header>
      <div
        className="fr-bmrows"
        style={{ maxHeight: Math.min(lanes.rows.length, VISIBLE_ROWS) * LANE_ROW + 4 }}
      >
        {lanes.rows.map((row) => (
          <BranchRow
            key={row.branch.name}
            row={row}
            width={lanes.width}
            chat={chats.get(row.branch.name) ?? null}
            color={map.color}
            onClick={() => {
              setNextDraftChoice(repo.name, branchChoice(row.branch));
              shell.newChat();
            }}
          />
        ))}
      </div>
    </section>
  );
}

const CHAT_WORDS: Record<BranchChat, string> = {
  running: "chat running",
  needsYou: "chat needs you",
  idle: "chat idle",
};

function BranchRow({
  row,
  width,
  chat,
  color,
  onClick,
}: {
  row: LaneRow;
  width: number;
  chat: BranchChat | null;
  color: (branch: string) => string | null;
  onClick: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const { branch } = row;
  const action = rowAction(branch);
  const lane = (name: string) => color(name) ?? "var(--t3)";
  const mid = LANE_ROW / 2;
  const x = laneX(row.depth);
  const own = lane(branch.name);
  return (
    <button
      className="fr-bmrow"
      title={action}
      aria-label={[branch.name, row.label, action, chat === null ? null : CHAT_WORDS[chat]]
        .filter(Boolean)
        .join(", ")}
      onPointerEnter={() => {
        setHovered(true);
      }}
      onPointerLeave={() => {
        setHovered(false);
      }}
      onClick={onClick}
    >
      <svg width={width} height={LANE_ROW} aria-hidden="true">
        {row.lines.map((line) => (
          <line
            key={`${line.lane}-${String(line.depth)}`}
            x1={laneX(line.depth)}
            x2={laneX(line.depth)}
            y1={line.fromMiddle ? mid : 0}
            y2={LANE_ROW}
            stroke={lane(line.lane)}
            strokeWidth="2"
            strokeLinecap="round"
          />
        ))}
        {row.depth > 0 && (
          <path
            d={`M${String(laneX(row.depth - 1))} 0C${String(laneX(row.depth - 1))} 12 ${String(x)} 8 ${String(x)} ${String(mid)}`}
            fill="none"
            stroke={own}
            strokeWidth="2"
            strokeLinecap="round"
          />
        )}
        {branch.here && <circle className="fr-pulse" cx={x} cy={mid} r="4.5" stroke={own} />}
        <circle cx={x} cy={mid} r={branch.here ? 5 : 4} fill={own} />
      </svg>
      <span className={branch.here ? "fr-bmname here" : "fr-bmname"}>{branch.name}</span>
      {row.label !== null && <small>{row.label}</small>}
      <span className="grow" />
      {hovered ? (
        <span className="fr-bmnew">
          <Icon name="plus" />
          New chat
        </span>
      ) : (
        chat !== null && <span className={`fr-bmdot ${chat}`} />
      )}
    </button>
  );
}
