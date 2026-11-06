// The new chat's "Work on" button and its picker (B96, P1, B131), as the Mac's WorkOnButton and
// PlacePickerList: Find, the top row pinned, every other branch in its lane with
// "New worktree" on hover, then what only the remotes have, in a popover; before the branch
// map loads, a menu offers the folder or a new worktree from its branch.
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { BranchMapBranch, RemoteBranch, RepoConfig } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { useApi } from "../context.ts";
import { BranchRow, DetachedRow } from "../shell/frame/BranchRow.tsx";
import { revealSelected, rowLane, type BranchChat } from "../shell/frame/branchLanes.ts";
import { FoundRows, RemoteFold, RemoteRow } from "../shell/frame/FlatRows.tsx";
import { FindField } from "../shell/frame/MapBar.tsx";
import { useBranchChats, useFreshWhenOpen } from "../shell/frame/projectMap.ts";
import { Menu } from "../ui/Menu.tsx";
import { Popover } from "../ui/Popover.tsx";
import { holdPicks, loadBranchMap, picksHeld, useBranchMap, type LoadedMap } from "./branchMaps.ts";
import { Glyph } from "./glyphs.tsx";
import {
  branchChoice,
  choiceTitle,
  inPlaceDetail,
  inPlaceTitle,
  isSelected,
  resolvedChoice,
  ROW_HEIGHT,
  VISIBLE_ROWS,
  WORKTREE_DETAIL,
  WORKTREE_TITLE,
  type NewChatChoice,
  type PickerRow,
} from "./placePicker.ts";

interface Props {
  repo: RepoConfig;
  choice: NewChatChoice;
  onChoose: (choice: NewChatChoice) => void;
  // The start screen's plain text, else the pane composer's capsule.
  quiet: boolean;
}

// Find and the full tree reach the others.
const REMOTE_ROWS = 40;

export function PlaceButton({ repo, choice, onChoose, quiet }: Props) {
  const { actions } = useStore();
  const loaded = useBranchMap(repo.name, repo.git);
  // The folder's branch may have changed in a terminal since the list was read.
  useEffect(() => {
    void actions.refreshRepo(repo.name);
  }, [actions, repo.name]);
  const title = choiceTitle(choice, repo);
  const lane = choice.kind === "worktree" ? (loaded?.color(choice.branch) ?? null) : null;
  const look = (open: boolean) => ({
    className: `dc-workon${quiet ? " quiet" : ""}${open ? " open" : ""}${lane === null ? "" : " lane"}`,
    style: lane === null ? undefined : { color: lane },
    title: "Where the chat works",
    "aria-label": `Where the chat works: ${title}`,
  });
  const label = (open: boolean) => (
    <>
      {(!quiet || lane !== null) && <Glyph name="branch" size={10} />}
      <span className="dc-workont">{title}</span>
      <Glyph name={open ? "chevronUp" : "chevron"} size={8} className="dc-workonc" />
    </>
  );

  if (loaded === null) {
    const shown = resolvedChoice(choice, repo).kind;
    return (
      <Menu
        label="Where this chat works"
        items={() => [
          { type: "section", title: "Where this chat works" },
          {
            title: inPlaceTitle(repo),
            detail: inPlaceDetail(repo),
            checked: shown === "inPlace",
            onSelect: () => {
              onChoose({ kind: "inPlace" });
            },
          },
          {
            title: WORKTREE_TITLE,
            detail: WORKTREE_DETAIL,
            checked: shown === "newWorktree",
            onSelect: () => {
              onChoose({ kind: "newWorktree", from: null });
            },
          },
        ]}
      >
        {(trigger, open) => (
          <button {...trigger} {...look(open)}>
            {label(open)}
          </button>
        )}
      </Menu>
    );
  }
  return (
    <PickerButton
      loaded={loaded}
      repo={repo}
      choice={choice}
      onChoose={onChoose}
      look={look}
      label={label}
    />
  );
}

function PickerButton({
  loaded,
  repo,
  choice,
  onChoose,
  look,
  label,
}: Omit<Props, "quiet"> & {
  loaded: LoadedMap;
  look: (open: boolean) => object;
  label: (open: boolean) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  useFreshWhenOpen(repo.name, repo.git, open);
  return (
    <>
      <button
        ref={button}
        {...look(open)}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
      >
        {label(open)}
      </button>
      {open && (
        <Popover
          anchor={button}
          label="Where this chat works"
          align="start"
          className="dc-placepop"
          onClose={() => {
            setOpen(false);
          }}
        >
          <PlaceList
            loaded={loaded}
            repo={repo}
            choice={choice}
            onChoose={(next) => {
              onChoose(next);
              setOpen(false);
            }}
          />
        </Popover>
      )}
    </>
  );
}

/** Find, the top row, then every other branch, scrolling past eight rows. */
function PlaceList({
  loaded,
  repo,
  choice,
  onChoose,
}: {
  loaded: LoadedMap;
  repo: RepoConfig;
  choice: NewChatChoice;
  onChoose: (choice: NewChatChoice) => void;
}) {
  const { actions } = useStore();
  const api = useApi();
  const { picker, map } = loaded;
  const chats = useBranchChats(repo, loaded);
  const [query, setQuery] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    revealSelected(box.current);
  }, []);
  const pickRemote = ({ remote, name }: RemoteBranch) =>
    holdPicks(repo.name, async () => {
      const made = await actions.trackRemoteBranch(repo.name, remote, name);
      if (made === null) return;
      await loadBranchMap(api, repo.name);
      onChoose({ kind: "onBranch", branch: made });
    });
  const pick = (branch: BranchMapBranch) => {
    if (branch.remote !== null) void pickRemote({ remote: branch.remote, name: branch.name });
    else if (!picksHeld(repo.name)) onChoose(branchChoice(branch));
  };
  const addWorktree = (branch: string) => {
    onChoose({ kind: "newWorktree", from: branch });
  };
  const row = (lane: PickerRow) => (
    <PlaceRow
      key={lane.branch.name}
      row={lane}
      loaded={loaded}
      selected={isSelected(lane.branch, choice, repo)}
      chat={chats.get(lane.branch.name) ?? null}
      onPick={pick}
      onAdd={addWorktree}
    />
  );
  const { detached } = map;
  const shown = detached ? picker.rows.length + 1 : picker.rows.length;
  return (
    <div className="dc-placel">
      <div className="dc-placef">
        <FindField value={query} placeholder="Where this chat works" onChange={setQuery} />
      </div>
      {query !== "" ? (
        <div className="fr-bmscroll placefound">
          <FoundRows
            map={map}
            query={query}
            picks={{
              selected: (branch) => isSelected(branch, choice, repo),
              color: loaded.color,
              onPick: pick,
              onRemote: (remote) => {
                void pickRemote(remote);
              },
              onAdd: addWorktree,
              addWord: "New worktree",
              tall: true,
            }}
          />
        </div>
      ) : (
        <>
          <div role="listbox" aria-label="Where this chat works">
            {picker.top !== null && row(picker.top)}
            <div
              ref={box}
              className="dc-placerows"
              style={{ height: Math.min(shown, VISIBLE_ROWS) * ROW_HEIGHT }}
            >
              {detached && (
                <DetachedRow
                  height={ROW_HEIGHT}
                  onClear={null}
                  trunk={
                    picker.rows.length > 0 && picker.top !== null
                      ? loaded.color(picker.top.branch.name)
                      : null
                  }
                />
              )}
              {picker.rows.map(row)}
            </div>
          </div>
          {map.remote_branches.length > 0 && <div className="dc-placediv" />}
          <RemoteFold count={map.remote_branches.length} rule={false}>
            <div className="fr-bmscroll placeremotes">
              {map.remote_branches.slice(0, REMOTE_ROWS).map((branch) => (
                <RemoteRow
                  key={`${branch.remote}/${branch.name}`}
                  branch={branch}
                  tall
                  onRemote={(remote) => {
                    void pickRemote(remote);
                  }}
                />
              ))}
            </div>
          </RemoteFold>
        </>
      )}
    </div>
  );
}

function PlaceRow({
  row,
  loaded,
  selected,
  chat,
  onPick,
  onAdd,
}: {
  row: PickerRow;
  loaded: LoadedMap;
  selected: boolean;
  chat: BranchChat | null;
  onPick: (branch: BranchMapBranch) => void;
  onAdd: (branch: string) => void;
}) {
  return (
    <BranchRow
      row={row}
      height={ROW_HEIGHT}
      ink={rowLane(row, loaded.color, selected, chat)}
      color={loaded.color}
      selected={selected}
      chat={null}
      behind={0}
      addWord={row.newWorktree === null ? null : "New worktree"}
      mono={row.branch.worktree !== null}
      label={row.words + (selected ? ", selected" : "")}
      option
      onPick={onPick}
      onAdd={onAdd}
    />
  );
}
