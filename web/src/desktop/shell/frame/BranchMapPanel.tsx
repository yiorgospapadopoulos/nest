import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { useReload, type LoadedMap } from "../../chat/branchMaps.ts";
import { Glyph } from "../../chat/glyphs.tsx";
import { useShell } from "../context.ts";
import { BranchRow, DetachedRow } from "./BranchRow.tsx";
import { BranchTreeSheet } from "./BranchTreeSheet.tsx";
import { LANE_ROW, mapRowLook, revealSelected, type LaneRow } from "./branchLanes.ts";
import { FoundRows, RemoteFold, RemoteRow } from "./FlatRows.tsx";
import { MapBar } from "./MapBar.tsx";
import { useBranchChats, useMapActions } from "./projectMap.ts";

// Under the pinned top row; the rest scroll.
const VISIBLE_ROWS = 5;
// Find and the full tree reach the others.
const REMOTE_ROWS = 60;

/**
 * The project's branches and worktrees as coloured lanes (B96, B131): the top row pinned,
 * every other branch scrolling under the branch it came from. A click selects where new
 * chats start and nothing else; where the project folder is pulses.
 */
export function BranchMapPanel({ map }: { map: LoadedMap }) {
  const { repo } = useShell();
  const reload = useReload(repo.name);
  const chats = useBranchChats(repo, map);
  const [query, setQuery] = useState("");
  const [tree, setTree] = useState(false);
  const [jump, setJump] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const reveal = useCallback(() => {
    setJump((n) => n + 1);
  }, []);
  const closeTree = useCallback(() => {
    setTree(false);
    setJump((n) => n + 1);
  }, []);
  const actions = useMapActions(reveal);
  useLayoutEffect(() => {
    revealSelected(box.current);
  }, [jump]);

  const { top, rest } = map.picker.lanes;
  const selected = repo.selected_place?.branch ?? null;
  const { detached } = map.map;
  const shown = rest.length + (detached ? 1 : 0);
  const row = (lane: LaneRow) => (
    <BranchRow
      key={lane.branch.name}
      height={LANE_ROW}
      onPick={actions.pick}
      onAdd={actions.addWorktree}
      {...mapRowLook(lane, map.color, selected, chats)}
    />
  );
  return (
    <section className="fr-bmap" aria-label="Branch map">
      <MapBar query={query} onQuery={setQuery} reload={reload}>
        <button
          className="fr-bmib"
          title="Full tree"
          aria-label="Full tree"
          onClick={() => {
            setTree(true);
          }}
        >
          <Glyph name="maximize" size={13} />
        </button>
      </MapBar>
      {query !== "" ? (
        <div className="fr-bmscroll found">
          <FoundRows
            map={map.map}
            query={query}
            picks={{
              selected: (branch) => branch.name === selected,
              color: map.color,
              onPick: (branch) => {
                actions.pickFound(branch);
                setQuery("");
              },
              onRemote: (remote) => {
                actions.pickRemote(remote);
                setQuery("");
              },
              onAdd: actions.addWorktree,
              addWord: "Worktree",
            }}
          />
        </div>
      ) : (
        <>
          {top !== null && row(top)}
          <div
            ref={box}
            className="fr-bmscroll"
            style={{ height: Math.min(shown, VISIBLE_ROWS) * LANE_ROW }}
          >
            {detached && (
              <DetachedRow
                height={LANE_ROW}
                trunk={rest.length > 0 && top !== null ? map.color(top.branch.name) : null}
                onClear={selected === null ? null : actions.clear}
              />
            )}
            {rest.map(row)}
          </div>
          <RemoteFold count={map.map.remote_branches.length} rule>
            <div className="fr-bmscroll remotes">
              {map.map.remote_branches.slice(0, REMOTE_ROWS).map((branch) => (
                <RemoteRow
                  key={`${branch.remote}/${branch.name}`}
                  branch={branch}
                  onRemote={actions.pickRemote}
                />
              ))}
            </div>
          </RemoteFold>
        </>
      )}
      {tree && (
        <BranchTreeSheet
          map={map}
          chats={chats}
          selected={selected}
          detached={detached}
          jump={jump}
          reload={reload}
          actions={actions}
          onClose={closeTree}
        />
      )}
    </section>
  );
}
