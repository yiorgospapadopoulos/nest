// A row of the branch map (B96, B131), for the small map, the full tree and the Work on
// picker: its lanes, its name, and what sits at its right.
import { memo } from "react";
import type { BranchMapBranch } from "../../../api/types.ts";
import { Icon } from "../../../ui/Icon.tsx";
import { Glyph } from "../../chat/glyphs.tsx";
import { laneX, selectedFill, type BranchChat, type LaneRow } from "./branchLanes.ts";

// Names longer than this can give way in the middle: the middle goes first, then the ending
// from its own front, and the start, which says most, stays.
const SPLIT_FROM = 14;
const TAIL = 8;
const START = 4;
// The least the middle holds, so a short one still fills the room of its ellipsis.
const MIDDLE = 5;

const CHAT_WORDS: Record<BranchChat, string> = {
  running: "chat running",
  needsYou: "chat needs you",
  idle: "chat idle",
};

/** One part of a name: `dim` of its characters grey, and what Find matched marked. */
function NamePart({
  text,
  className,
  dim,
  from,
  to,
}: {
  text: string;
  className: string;
  dim: number;
  from: number;
  to: number;
}) {
  return (
    <span className={className}>
      {to > from ? (
        <>
          {text.slice(0, from)}
          <em>{text.slice(from, to)}</em>
          {text.slice(to)}
        </>
      ) : (
        <>
          {dim > 0 && <span className="fr-bmpre">{text.slice(0, dim)}</span>}
          {text.slice(dim)}
        </>
      )}
    </span>
  );
}

/** A branch name that gives way in the middle at any width. */
export function MiddleName({
  name,
  className,
  query = "",
  dim = false,
}: {
  name: string;
  className?: string;
  query?: string;
  dim?: boolean;
}) {
  const at = query === "" ? -1 : name.toLowerCase().indexOf(query.toLowerCase());
  const end = at === -1 ? -1 : at + query.length;
  const tail = name.length > SPLIT_FROM ? name.length - TAIL : name.length;
  const start = Math.min(START, tail - MIDDLE);
  const folders = dim && at === -1 ? name.lastIndexOf("/", tail - 1) + 1 : 0;
  const part = (from: number, to: number, kind: string) => (
    <NamePart
      text={name.slice(from, to)}
      className={kind}
      dim={Math.min(Math.max(folders - from, 0), to - from)}
      from={Math.max(at, from) - from}
      to={Math.min(end, to) - from}
    />
  );
  return (
    <span className={className === undefined ? "fr-mid" : `fr-mid ${className}`}>
      {tail === name.length ? (
        part(0, tail, "fr-midw")
      ) : (
        <>
          {part(0, start, "fr-mids")}
          {part(start, tail, "fr-midm")}
          <span className="fr-mide">
            {Array.from(name.slice(tail))
              .reverse()
              .map((letter, index) => {
                const position = name.length - 1 - index;
                return position >= at && position < end ? (
                  <em key={position}>{letter}</em>
                ) : (
                  <span key={position}>{letter}</span>
                );
              })}
          </span>
        </>
      )}
    </span>
  );
}

/** The lanes through a row and its node: filled for a worktree, dotted for a remote branch. */
function LaneGraph({
  row,
  height,
  ink,
  color,
}: {
  row: LaneRow;
  height: number;
  ink: string;
  color: (branch: string) => string | null;
}) {
  const { branch, parentDepth } = row;
  const mid = height / 2;
  const x = laneX(row.depth);
  const here = branch.here;
  return (
    <svg className="fr-lanes" width={x + 14} height={height} aria-hidden="true">
      {row.lines.map((line) => (
        <line
          key={line.lane}
          x1={laneX(line.depth)}
          x2={laneX(line.depth)}
          y1={line.fromMiddle ? mid : 0}
          y2={height}
          stroke={color(line.lane) ?? "var(--t3)"}
          strokeWidth="2"
          strokeLinecap="round"
        />
      ))}
      {parentDepth === row.depth ? (
        <line x1={x} x2={x} y1={0} y2={mid} stroke={ink} strokeWidth="2" strokeLinecap="round" />
      ) : (
        parentDepth !== null && (
          <path
            d={`M${String(laneX(parentDepth))} 0C${String(laneX(parentDepth))} ${String(mid - 5)} ${String(x)} ${String(mid - 9)} ${String(x)} ${String(mid)}`}
            fill="none"
            stroke={ink}
            strokeWidth="2"
            strokeLinecap="round"
          />
        )
      )}
      {here && <circle className="fr-pulse" cx={x} cy={mid} r="4.5" stroke={ink} />}
      {branch.remote !== null ? (
        <circle
          className="fr-node"
          cx={x}
          cy={mid}
          r="3.4"
          stroke={ink}
          strokeWidth="1.6"
          strokeDasharray="1.8 2"
        />
      ) : branch.worktree !== null || here ? (
        <circle cx={x} cy={mid} r={here ? 5 : 4} fill={ink} />
      ) : (
        <circle className="fr-node" cx={x} cy={mid} r="3.2" stroke={ink} strokeWidth="1.8" />
      )}
    </svg>
  );
}

/** The new worktree button, which takes the row's right end on hover. */
export function AddWorktree({
  branch,
  word,
  onAdd,
}: {
  branch: string;
  word: string;
  onAdd: (branch: string) => void;
}) {
  return (
    <button
      className="fr-bmadd"
      aria-label={`New worktree from ${branch}`}
      onClick={(event) => {
        event.stopPropagation();
        onAdd(branch);
      }}
    >
      <Icon name="plus" />
      {word}
    </button>
  );
}

/** The mark on the selected row, in the row's colour. */
export function SelectedCheck({ ink }: { ink: string }) {
  return (
    <span className="fr-bmx fr-bmck" style={{ color: ink }}>
      <Glyph name="check" size={11} />
    </span>
  );
}

function rowWords(row: LaneRow, chat: BranchChat | null, behind: number): string {
  const { branch } = row;
  return [
    branch.name,
    row.label,
    branch.remote === null ? null : `only on ${branch.remote}`,
    behind > 0 ? `${String(behind)} behind` : null,
    chat === null ? null : CHAT_WORDS[chat],
  ]
    .filter(Boolean)
    .join(", ");
}

interface RowProps {
  row: LaneRow;
  height: number;
  // The row's own lane, from rowLane.
  ink: string;
  color: (branch: string) => string | null;
  selected: boolean;
  chat: BranchChat | null;
  // The commits to note as behind; 0 for no note.
  behind: number;
  // The new worktree button's word; null on a row that has none.
  addWord: string | null;
  // A row of the full tree: its whole name, with nothing pushed to the right.
  wide?: boolean;
  mono?: boolean;
  // What the row is called; the map's rows say it from the rest.
  label?: string;
  // A row of the picker's list.
  option?: boolean;
  onPick: (branch: BranchMapBranch) => void;
  onAdd: (branch: string) => void;
}

export const BranchRow = memo(function BranchRow({
  row,
  height,
  ink,
  color,
  selected,
  chat,
  behind,
  addWord,
  wide = false,
  mono = false,
  label,
  option = false,
  onPick,
  onAdd,
}: RowProps) {
  const { branch, fromParent } = row;
  const nameClass = `fr-bmname${branch.here ? " here" : ""}${mono ? " mono" : ""}`;
  const name = wide ? (
    <span className={nameClass}>{branch.name}</span>
  ) : (
    <MiddleName name={branch.name} className={nameClass} />
  );
  return (
    <div
      className={`fr-bmrow${selected ? " on" : ""}${wide ? " wide" : ""}${addWord === null ? "" : " adds"}`}
      style={{ height, ...(selected ? selectedFill(ink) : {}) }}
      onClick={() => {
        onPick(branch);
      }}
    >
      <button
        className="fr-bmpick"
        title={branch.name}
        aria-label={label ?? rowWords(row, chat, behind)}
        {...(option ? { role: "option", "aria-selected": selected } : {})}
        aria-current={selected && !option ? "true" : undefined}
      >
        <LaneGraph row={row} height={height} ink={ink} color={color} />
        {fromParent === null ? (
          name
        ) : (
          <span className="fr-bmtwo">
            {name}
            <MiddleName name={`from ${fromParent}`} className="fr-bmfrom" />
          </span>
        )}
        {row.label !== null && <small>{row.label}</small>}
        {branch.remote !== null && <small>{branch.remote}</small>}
        {!wide && <span className="grow" />}
        {behind > 0 && <small className="fr-bmx fr-bmbehind">{behind} behind</small>}
        {chat !== null && <span className={`fr-bmx fr-bmdot ${chat}`} />}
        {selected && <SelectedCheck ink={ink} />}
      </button>
      {addWord !== null && <AddWorktree branch={branch.name} word={addWord} onAdd={onAdd} />}
    </div>
  );
});

/** The project folder on a detached HEAD; with `onClear`, a click goes back to the folder. */
export function DetachedRow({
  height,
  trunk,
  onClear,
}: {
  height: number;
  trunk: string | null;
  onClear: (() => void) | null;
}) {
  const mid = height / 2;
  const x = laneX(1);
  const parts = (
    <>
      <svg className="fr-lanes" width={x + 14} height={height} aria-hidden="true">
        {trunk !== null && (
          <line
            x1={laneX(0)}
            x2={laneX(0)}
            y1={0}
            y2={height}
            stroke={trunk}
            strokeWidth="2"
            strokeLinecap="round"
          />
        )}
        <circle className="fr-pulse" cx={x} cy={mid} r="4.5" stroke="var(--t3)" />
        <circle cx={x} cy={mid} r="5" fill="var(--t3)" />
      </svg>
      <span className="fr-bmname">detached</span>
      <small>here</small>
    </>
  );
  return (
    <div className="fr-bmrow fixed" style={{ height }}>
      {onClear === null ? (
        <div className="fr-bmpick">{parts}</div>
      ) : (
        <button className="fr-bmpick" aria-label="detached, here" onClick={onClear}>
          {parts}
        </button>
      )}
    </div>
  );
}
