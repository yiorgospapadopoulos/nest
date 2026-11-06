import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { LoadedMap, Reload } from "../../chat/branchMaps.ts";
import { SheetFrame } from "../../sheets/SheetFrame.tsx";
import { BranchRow, DetachedRow } from "./BranchRow.tsx";
import {
  LANE_ROW,
  mapRowLook,
  revealSelected,
  type BranchChat,
  type LaneRow,
} from "./branchLanes.ts";
import { FoundRows, RemoteRow } from "./FlatRows.tsx";
import { MapBar } from "./MapBar.tsx";
import type { MapActions } from "./projectMap.ts";

const WIDTH = 720;
const HEIGHT = 560;

/**
 * Everything in one sheet (B131): every level with no indent cap, worktrees and remotes,
 * scrolling both ways under a pinned top row. A click selects as in the small map and the
 * sheet stays open with the mark moving.
 */
export function BranchTreeSheet({
  map,
  chats,
  selected,
  detached,
  jump,
  reload,
  actions,
  onClose,
}: {
  map: LoadedMap;
  chats: Map<string, BranchChat>;
  selected: string | null;
  detached: boolean;
  // Goes up when a selection that needs showing has landed.
  jump: number;
  reload: Reload;
  actions: MapActions;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    revealSelected(box.current, true);
  }, [jump]);
  const { top, rest } = map.tree;
  // The draft opens under the sheet, so the sheet makes way for it.
  const addWorktree = useCallback(
    (branch: string) => {
      onClose();
      actions.addWorktree(branch);
    },
    [actions, onClose],
  );
  const row = (lane: LaneRow) => (
    <BranchRow
      key={lane.branch.name}
      height={LANE_ROW}
      wide
      onPick={actions.pick}
      onAdd={addWorktree}
      {...mapRowLook(lane, map.color, selected, chats)}
    />
  );
  return (
    <SheetFrame
      title="Branches and worktrees"
      width={WIDTH}
      maxHeight={HEIGHT}
      className="fr-bmsheet"
      onClose={onClose}
    >
      <MapBar query={query} onQuery={setQuery} reload={reload} />
      <div ref={box} className="fr-bmtree">
        <div className="fr-bmtreein">
          {query !== "" ? (
            <FoundRows
              map={map.map}
              query={query}
              picks={{
                selected: (branch) => branch.name === selected,
                color: map.color,
                onPick: actions.pickFound,
                onRemote: actions.pickRemote,
                onAdd: addWorktree,
                addWord: "Worktree",
                tall: true,
              }}
            />
          ) : (
            <>
              {top !== null && <div className="fr-bmstuck">{row(top)}</div>}
              {detached && (
                <DetachedRow
                  height={LANE_ROW}
                  trunk={rest.length > 0 && top !== null ? map.color(top.branch.name) : null}
                  onClear={selected === null ? null : actions.clear}
                />
              )}
              {rest.map(row)}
              {map.map.remote_branches.length > 0 && <div className="fr-bmgap" />}
              {map.map.remote_branches.map((branch) => (
                <RemoteRow
                  key={`${branch.remote}/${branch.name}`}
                  branch={branch}
                  tall
                  onRemote={actions.pickRemote}
                />
              ))}
            </>
          )}
        </div>
      </div>
    </SheetFrame>
  );
}
