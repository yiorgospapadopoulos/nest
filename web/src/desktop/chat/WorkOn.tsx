// The new chat's "Work on" button and its picker (B96, P1), as the Mac's WorkOnButton and
// PlacePickerList: the project's branches with their lanes, each with "New worktree from"
// it and its worktrees, in a popover; before the branch map loads, a menu offers the
// folder or a new worktree from its branch.
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { RepoConfig } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Menu } from "../ui/Menu.tsx";
import { Popover } from "../ui/Popover.tsx";
import { useBranchMap, type LoadedMap } from "./branchMaps.ts";
import { Glyph } from "./glyphs.tsx";
import {
  choiceTitle,
  DIVIDER_HEIGHT,
  inPlaceDetail,
  inPlaceTitle,
  laneX,
  resolvedChoice,
  ROW_HEIGHT,
  sameChoice,
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
    const inPlace = choice.kind === "inPlace";
    return (
      <Menu
        label="Where this chat works"
        items={() => [
          { type: "section", title: "Where this chat works" },
          {
            title: inPlaceTitle(repo),
            detail: inPlaceDetail(repo),
            checked: inPlace,
            onSelect: () => {
              onChoose({ kind: "inPlace" });
            },
          },
          {
            title: WORKTREE_TITLE,
            detail: WORKTREE_DETAIL,
            checked: !inPlace,
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
  const selected = resolvedChoice(choice, repo);
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
            selected={selected}
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

/** "Where this chat works", then a block per branch, divided; it scrolls past eleven rows. */
function PlaceList({
  loaded,
  selected,
  onChoose,
}: {
  loaded: LoadedMap;
  selected: NewChatChoice;
  onChoose: (choice: NewChatChoice) => void;
}) {
  const { picker } = loaded;
  return (
    <div className="dc-placel">
      <span className="dc-placeh">Where this chat works</span>
      <div
        className="dc-placerows"
        style={{ maxHeight: picker.height }}
        role="listbox"
        aria-label="Where this chat works"
      >
        {picker.blocks.map((block, index) => (
          <div key={block.id}>
            {index > 0 && <div className="dc-placediv" style={{ height: DIVIDER_HEIGHT }} />}
            {block.rows.map((row) => (
              <PlaceRow
                key={row.id}
                row={row}
                width={picker.width}
                loaded={loaded}
                selected={sameChoice(row.choice, selected)}
                onChoose={onChoose}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function PlaceRow({
  row,
  width,
  loaded,
  selected,
  onChoose,
}: {
  row: PickerRow;
  width: number;
  loaded: LoadedMap;
  selected: boolean;
  onChoose: (choice: NewChatChoice) => void;
}) {
  const color = (branch: string) => loaded.color(branch) ?? "var(--t3)";
  const own = color(row.branch);
  const mid = ROW_HEIGHT / 2;
  const x = laneX(row.depth);
  const radius = row.kind === "worktree" ? 3.5 : row.kind === "folder" ? 4.5 : 4;
  return (
    <button
      role="option"
      aria-selected={selected}
      aria-label={row.label + (selected ? ", selected" : "")}
      className={`dc-placer ${row.kind}${selected ? " on" : ""}`}
      style={selected ? { background: `color-mix(in srgb, ${own} 14%, transparent)` } : undefined}
      onClick={() => {
        onChoose(row.choice);
      }}
    >
      <svg width={width} height={ROW_HEIGHT} aria-hidden="true" className="dc-lanes">
        {row.lines.map((line, index) => (
          <line
            key={index}
            x1={laneX(line.depth)}
            x2={laneX(line.depth)}
            y1={line.fromTop ? 0 : mid}
            y2={line.toBottom ? ROW_HEIGHT : mid}
            stroke={color(line.lane)}
            strokeWidth={2}
            strokeLinecap="round"
          />
        ))}
        {row.parentDepth !== null && (
          <path
            d={`M${String(laneX(row.parentDepth))} 0 C${String(laneX(row.parentDepth))} 10 ${String(x)} 6 ${String(x)} ${String(mid)}`}
            fill="none"
            stroke={own}
            strokeWidth={2}
            strokeLinecap="round"
          />
        )}
        {row.kind === "newWorktree" ? (
          <path
            d={`M${String(laneX(row.depth + 1) - 4)} ${String(mid)}h8M${String(laneX(row.depth + 1))} ${String(mid - 4)}v8`}
            stroke="var(--t2)"
            strokeWidth={1.6}
            strokeLinecap="round"
          />
        ) : (
          <circle cx={x} cy={mid} r={radius} fill={own} />
        )}
      </svg>
      <span className="dc-placet">{row.title}</span>
      {row.detail !== null && <span className="dc-placed">{row.detail}</span>}
      <span className="grow" />
      {selected && (
        <span style={{ color: own }} className="dc-placeck">
          <Glyph name="check" size={10} />
        </span>
      )}
    </button>
  );
}
