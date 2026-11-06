// The map's flat rows, for Find and the remotes (B131): no lanes, a branch by its name, a
// remote branch naming its remote.
import { useState, type ReactNode } from "react";
import type { BranchMap, BranchMapBranch, RemoteBranch } from "../../../api/types.ts";
import { Glyph } from "../../chat/glyphs.tsx";
import { AddWorktree, MiddleName, SelectedCheck } from "./BranchRow.tsx";
import { findPlaces, selectedFill } from "./branchLanes.ts";

export interface FoundPicks {
  selected: (branch: BranchMapBranch) => boolean;
  color: (branch: string) => string | null;
  onPick: (branch: BranchMapBranch) => void;
  onRemote: (remote: RemoteBranch) => void;
  onAdd: (branch: string) => void;
  addWord: string;
  // The 30 high rows of the sheet and the picker, else 26.
  tall?: boolean;
}

function FlatNode({ fill, dotted }: { fill: string | null; dotted: boolean }) {
  return (
    <svg width="28" height="14" aria-hidden="true">
      {fill !== null ? (
        <circle cx="14" cy="7" r="3.5" fill={fill} />
      ) : (
        <circle
          cx="14"
          cy="7"
          r="3"
          fill="none"
          stroke="var(--t3)"
          strokeWidth="1.4"
          {...(dotted ? { strokeDasharray: "1.6 1.9" } : {})}
        />
      )}
    </svg>
  );
}

function FlatBranch({
  branch,
  query,
  picks,
}: {
  branch: BranchMapBranch;
  query: string;
  picks: FoundPicks;
}) {
  const selected = picks.selected(branch);
  const ink = picks.color(branch.name) ?? "var(--t3)";
  const local = branch.remote === null;
  return (
    <div
      className={`fr-bmflat${picks.tall === true ? " tall" : ""}${selected ? " on" : ""}${local ? " adds" : ""}`}
      style={selected ? selectedFill(ink) : undefined}
      onClick={() => {
        picks.onPick(branch);
      }}
    >
      <button className="fr-bmpick" title={branch.name} aria-label={branch.name}>
        <FlatNode fill={branch.worktree === null ? null : ink} dotted={!local} />
        <MiddleName name={branch.name} className="fr-bmname" query={query} />
        <span className="grow" />
        {!local && <small>{branch.remote}</small>}
        {selected && <SelectedCheck ink={ink} />}
      </button>
      {local && <AddWorktree branch={branch.name} word={picks.addWord} onAdd={picks.onAdd} />}
    </div>
  );
}

/** A branch only a remote has; picking it makes the local branch. */
export function RemoteRow({
  branch,
  query = "",
  tall = false,
  onRemote,
}: {
  branch: RemoteBranch;
  query?: string;
  tall?: boolean;
  onRemote: (remote: RemoteBranch) => void;
}) {
  return (
    <div
      className={`fr-bmflat${tall ? " tall" : ""}`}
      onClick={() => {
        onRemote(branch);
      }}
    >
      <button
        className="fr-bmpick"
        title={`${branch.remote}/${branch.name}`}
        aria-label={`${branch.name} on ${branch.remote}`}
      >
        <FlatNode fill={null} dotted />
        <MiddleName name={branch.name} className="fr-bmname" query={query} dim />
        <span className="grow" />
        <small>{branch.remote}</small>
      </button>
    </div>
  );
}

/** What Find found: branches first, then what only a remote has. */
export function FoundRows({
  map,
  query,
  picks,
}: {
  map: BranchMap;
  query: string;
  picks: FoundPicks;
}) {
  const found = findPlaces(map, query);
  if (found.branches.length === 0 && found.remotes.length === 0) {
    return <div className="fr-bmfold quiet">No branch has that name</div>;
  }
  return (
    <>
      {found.branches.map((branch) => (
        <FlatBranch key={branch.name} branch={branch} query={query} picks={picks} />
      ))}
      {found.remotes.map((branch) => (
        <RemoteRow
          key={`${branch.remote}/${branch.name}`}
          branch={branch}
          query={query}
          tall={picks.tall === true}
          onRemote={picks.onRemote}
        />
      ))}
    </>
  );
}

/** The folded "On remotes" row and, opened, what is under it; no remotes, no row. */
export function RemoteFold({
  count,
  rule,
  children,
}: {
  count: number;
  // A line over it, in the small map.
  rule: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  if (count === 0) return null;
  return (
    <>
      <button
        className={`fr-bmfold${rule ? " rule" : ""}${open ? " open" : ""}`}
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
      >
        <Glyph name="chevron" size={10} />
        On remotes
        <span className="grow" />
        <small>{count}</small>
      </button>
      {open && children}
    </>
  );
}
