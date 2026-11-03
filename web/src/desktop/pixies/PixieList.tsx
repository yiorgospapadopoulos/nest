import { createContext, use, useRef, useState, type DragEvent, type ReactNode } from "react";
import type { Pixie } from "../../api/types.ts";
import { usePending } from "../../screens/pixies/pending.ts";
import { useStore } from "../../store/context.ts";
import { pixieWorking, unreadActions } from "../../store/selectors.ts";
import { leaderColor } from "../../transcript/mentions.ts";
import { Confirm } from "../sheets/Alert.tsx";
import { useShell } from "../shell/context.ts";
import { PANE_DRAG } from "../shell/bits.tsx";
import { useContextMenu } from "../ui/contextMenu.tsx";
import { Button } from "../ui/controls.tsx";
import { RenameField } from "../ui/RenameField.tsx";
import { CountBadge, RowActionsMenu, StatusDot } from "./bits.tsx";
import { PxGlyph, type PxGlyphName } from "./glyphs.tsx";
import { pixieMenu, teamMenu } from "./listMenus.ts";
import { listedPixies, listSections, movedBy, placement, type TeamSection } from "./order.ts";
import { PromptSheet } from "./PromptSheet.tsx";
import { useShowsHandle } from "./rowFit.ts";
import { ReportsInbox } from "./ReportsInbox.tsx";
import { Sprite } from "./Sprite.tsx";
import { CONFIRM, type TeamPrompt } from "./words.ts";
import "./pixies.css";

// A pixie dragged from the list, for the rows and headers it is dragged over.
const PIXIE_DRAG = "application/x-nest-pixie";

type Asked = { prompt: TeamPrompt } | { deletePixie: string } | { deleteTeam: string };

interface ListState {
  // Every pixie's id in the order shown, hidden ones too: a reorder names them all.
  order: string[];
  setOrder: (order: string[]) => void;
  dragged: string | null;
  setDragged: (id: string | null) => void;
  ask: (asked: Asked) => void;
  renaming: string | null;
  setRenaming: (team: string | null) => void;
}

const ListContext = createContext<ListState | null>(null);

function useList(): ListState {
  const list = use(ListContext);
  if (list === null) throw new Error("useList outside the pixie list");
  return list;
}

/**
 * The pixies down the left, as the sidebar lists chats (PixieList.swift): the title, New
 * pixie and New team, the reports, then teams as foldable sections with their pixies (the
 * leader marked) and the pixies with no team (B40). A click opens a pixie's pane; drag one
 * onto the workspace to split it like a chat, onto another pixie to put it there (joining
 * that one's team), onto a team's header to join it, or onto No team to leave its team.
 * Each pixie and team has a menu under ⋯ and on a right click.
 */
export function PixieList() {
  const { state, actions } = useStore();
  const shell = useShell();
  const [order, setOrder] = usePending(
    listedPixies(state.pixies, true).map((p) => p.id),
    (ids) => actions.reorderPixies(ids),
  );
  const [dragged, setDragged] = useState<string | null>(null);
  const [asked, ask] = useState<Asked | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);

  const listed = order.flatMap((id) => {
    const p = state.pixies[id];
    return p === undefined || (p.hidden && !shell.showsHiddenPixies) ? [] : [p];
  });
  const sections = listSections(listed, Object.values(state.teams));
  const hidden = Object.values(state.pixies).filter((p) => p.hidden).length;
  const done = () => {
    ask(null);
  };

  return (
    <ListContext value={{ order, setOrder, dragged, setDragged, ask, renaming, setRenaming }}>
      <div className="px-title">Pixies</div>
      <div className="px-new">
        <NewButton
          title="New pixie"
          icon="plus"
          onClick={() => {
            shell.createPixie({ name: "New pixie" }, true);
          }}
        />
        <NewButton
          title="New team"
          icon="team"
          onClick={() => {
            ask({ prompt: { kind: "new" } });
          }}
        />
      </div>
      <div className="dk-scroll px-scroll">
        <ReportsInbox />
        {sections.teams.map((section) => (
          <TeamGroup key={section.team.id} section={section} />
        ))}
        <LooseGroup pixies={sections.loose} titled={sections.teams.length > 0} />
      </div>
      {hidden > 0 && (
        <div className="px-hidden">
          <Button
            kind="plain"
            onClick={() => {
              shell.setShowsHiddenPixies(!shell.showsHiddenPixies);
            }}
          >
            <PxGlyph name={shell.showsHiddenPixies ? "eyeSlash" : "eye"} />
            {shell.showsHiddenPixies ? "Hide hidden" : `Show hidden (${String(hidden)})`}
          </Button>
        </div>
      )}
      {asked !== null && "prompt" in asked && <PromptSheet prompt={asked.prompt} onClose={done} />}
      {asked !== null && "deletePixie" in asked && (
        <DeleteConfirm
          what={CONFIRM.deletePixie(state.pixies[asked.deletePixie]?.name ?? "the pixie")}
          onConfirm={() => {
            done();
            void actions.deletePixie(asked.deletePixie);
          }}
          onCancel={done}
        />
      )}
      {asked !== null && "deleteTeam" in asked && (
        <DeleteConfirm
          what={CONFIRM.deleteTeam(state.teams[asked.deleteTeam]?.name ?? "the team")}
          onConfirm={() => {
            done();
            void actions.deleteTeam(asked.deleteTeam);
          }}
          onCancel={done}
        />
      )}
    </ListContext>
  );
}

function DeleteConfirm({
  what,
  onConfirm,
  onCancel,
}: {
  what: { title: string; message: string };
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Confirm
      destructive
      title={what.title}
      message={what.message}
      action="Delete"
      onConfirm={onConfirm}
      onClose={onCancel}
    />
  );
}

/** New pixie or New team, side by side under the title. */
function NewButton({
  title,
  icon,
  onClick,
}: {
  title: string;
  icon: PxGlyphName;
  onClick: () => void;
}) {
  return (
    <button className="px-newb" onClick={onClick}>
      <PxGlyph name={icon} />
      {title}
    </button>
  );
}

/** Takes a pixie dragged from the list; `drop` gets its id. */
function useDropTarget(drop: (id: string) => void) {
  const { dragged, setDragged } = useList();
  const [targeted, setTargeted] = useState(false);
  const props = {
    onDragOver: (event: DragEvent) => {
      if (dragged === null || !event.dataTransfer.types.includes(PIXIE_DRAG)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      if (!targeted) setTargeted(true);
    },
    onDragLeave: (event: DragEvent) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setTargeted(false);
    },
    onDrop: (event: DragEvent) => {
      setTargeted(false);
      if (dragged === null) return;
      event.preventDefault();
      drop(dragged);
      setDragged(null);
    },
  };
  return { targeted: targeted && dragged !== null, props };
}

/** A team: its header, then its pixies unless folded. */
function TeamGroup({ section }: { section: TeamSection }) {
  const { state } = useStore();
  const folded = state.foldedTeams.includes(section.team.id);
  const ids = section.members.map((p) => p.id);
  return (
    <div className="px-team" role="group" aria-label={`Team ${section.team.name}`}>
      <TeamHeader section={section} folded={folded} />
      {!folded && (
        <>
          {section.members.map((p) => (
            <PixieRow key={p.id} pixie={p} listed={ids} leader={section.team.leader_id === p.id} />
          ))}
          {section.members.length === 0 && <p className="px-dragnote">Drag pixies here</p>}
        </>
      )}
    </div>
  );
}

/** Fold chevron, name and @handle; ⋯ on hover and a right click open its menu. */
function TeamHeader({ section, folded }: { section: TeamSection; folded: boolean }) {
  const { state, actions } = useStore();
  const { ask, renaming, setRenaming } = useList();
  const team = section.team;
  const [menuOpen, setMenuOpen] = useState(false);
  const drop = useDropTarget((id) => void actions.updatePixie(id, { team_id: team.id }));
  const items = () =>
    teamMenu(section, {
      rename: () => {
        setRenaming(team.id);
      },
      changeHandle: () => {
        ask({ prompt: { kind: "handle", team: team.id } });
      },
      setLeader: (pixie) => void actions.updateTeam(team.id, { leader_id: pixie }),
      remove: () => {
        ask({ deleteTeam: team.id });
      },
    });
  const context = useContextMenu(team.name, items);
  const color = leaderColor(team, state.pixies);
  const toggle = () => {
    actions.setTeamFolded(team.id, !folded);
  };
  const renamingThis = renaming === team.id;
  return (
    <div
      className={`px-thead${drop.targeted ? " targeted" : ""}${menuOpen || context.open ? " menu" : ""}`}
      {...drop.props}
      onContextMenu={context.onContextMenu}
    >
      <button
        className="px-tbtn"
        aria-expanded={!folded}
        aria-label={`Team ${team.name}, @${team.handle}, ${String(section.members.length)} pixies${folded ? ", folded" : ""}`}
        onClick={toggle}
      >
        <PxGlyph name="chevronDown" className="px-tchev" />
        {renamingThis ? (
          <RenameField
            value={team.name}
            label="Team name"
            className="px-trename"
            onCommit={(name) => {
              setRenaming(null);
              void actions.updateTeam(team.id, { name });
            }}
            onCancel={() => {
              setRenaming(null);
            }}
          />
        ) : (
          <span className="px-tname" style={color === null ? undefined : { color }}>
            {team.name}
          </span>
        )}
        {!renamingThis && <span className="px-thandle">@{team.handle}</span>}
      </button>
      {!renamingThis && (
        <span className="px-tacts">
          <RowActionsMenu title={team.name} items={items} onOpenChange={setMenuOpen} />
        </span>
      )}
      {context.menu}
    </div>
  );
}

/** The pixies with no team; titled No team below teams, where a dropped pixie leaves its team. */
function LooseGroup({ pixies, titled }: { pixies: Pixie[]; titled: boolean }) {
  const { actions } = useStore();
  const drop = useDropTarget((id) => void actions.updatePixie(id, { team_id: null }));
  return (
    <div className="px-loose" role="group" aria-label={titled ? "No team" : "Pixies"}>
      {titled && (
        <div className={`px-nohead${drop.targeted ? " targeted" : ""}`} {...drop.props}>
          No team
        </div>
      )}
      {pixies.map((p) => (
        <PixieRow key={p.id} pixie={p} listed={pixies.map((each) => each.id)} leader={false} />
      ))}
    </div>
  );
}

/**
 * A pixie: its sprite, name and @slug, Leader for its team's leader; a dot while it works
 * and a count of what waits for the user. Selected while its pane has focus, softly filled
 * while it is open; ⋯ on hover opens its menu.
 */
function PixieRow({ pixie, listed, leader }: { pixie: Pixie; listed: string[]; leader: boolean }) {
  const { state, actions } = useStore();
  const shell = useShell();
  const list = useList();
  const [menuOpen, setMenuOpen] = useState(false);
  const rowState = shell.state.layout.rowState(pixie.id);
  const running = pixieWorking(state, pixie);
  const waiting =
    Object.values(state.approvals).filter((a) => a.repo === `pixie:${pixie.id}`).length +
    unreadActions(state, pixie.id);
  const drop = useDropTarget((id) => {
    const ordered = list.order.flatMap((each) => state.pixies[each] ?? []);
    const place = placement(ordered, id, pixie.id);
    if (place === null) return;
    if (place.team !== undefined) void actions.updatePixie(id, { team_id: place.team });
    if (place.order !== null) list.setOrder(place.order);
  });
  const draggedIndex = list.dragged === null ? -1 : list.order.indexOf(list.dragged);
  const below = draggedIndex !== -1 && draggedIndex < list.order.indexOf(pixie.id);
  const items = () =>
    pixieMenu(
      pixie,
      listed,
      Object.values(state.teams).sort((a, b) => a.position - b.position),
      {
        open: () => {
          shell.openPixie(pixie.id);
        },
        details: () => {
          shell.showPixieDetails(pixie.id);
        },
        duplicate: () => {
          void actions.duplicatePixie(pixie.id).then((copy) => {
            if (copy !== null) actions.toast(`Duplicated as ${copy.name}`);
          });
        },
        setTeam: (team) => void actions.updatePixie(pixie.id, { team_id: team }),
        move: (offset) => {
          const next = movedBy(list.order, pixie.id, offset, listed);
          if (next !== null) list.setOrder(next);
        },
        setHidden: (hidden) => void actions.updatePixie(pixie.id, { hidden }),
        remove: () => {
          list.ask({ deletePixie: pixie.id });
        },
      },
    );
  const context = useContextMenu(pixie.name, items);
  const labelRef = useRef<HTMLSpanElement>(null);
  const handle = pixie.hidden ? `@${pixie.slug} · Hidden` : `@${pixie.slug}`;
  const handleShown = useShowsHandle(labelRef, `${pixie.name} ${handle} ${String(leader)}`);
  const onDragStart = (event: DragEvent) => {
    // The same drag as a sidebar chat's, so the workspace takes it like one.
    event.dataTransfer.setData(PANE_DRAG, pixie.id);
    event.dataTransfer.setData(PIXIE_DRAG, pixie.id);
    event.dataTransfer.effectAllowed = "move";
    list.setDragged(pixie.id);
  };
  const label = [
    pixie.name,
    `@${pixie.slug}`,
    leader ? "leader" : null,
    running ? "running" : null,
    waiting > 0 ? `${String(waiting)} need you` : null,
    rowState !== "closed" ? "open" : null,
  ]
    .filter(Boolean)
    .join(", ");
  const classes = [
    "px-row",
    rowState,
    pixie.hidden ? "hidden" : "",
    list.dragged === pixie.id ? "dragging" : "",
    drop.targeted && list.dragged !== pixie.id ? (below ? "drop-below" : "drop-above") : "",
    menuOpen || context.open ? "menu" : "",
  ];
  return (
    <div
      className={classes.filter(Boolean).join(" ")}
      draggable
      onDragStart={onDragStart}
      onDragEnd={() => {
        list.setDragged(null);
      }}
      {...drop.props}
      onContextMenu={context.onContextMenu}
    >
      <button
        className="px-rowbtn"
        aria-label={label}
        aria-current={rowState === "focused" ? "true" : undefined}
        onClick={() => {
          shell.openPixie(pixie.id);
        }}
        onKeyDown={(event) => {
          if (!event.altKey || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
          event.preventDefault();
          const next = movedBy(list.order, pixie.id, event.key === "ArrowUp" ? -1 : 1, listed);
          if (next !== null) list.setOrder(next);
        }}
      >
        <span className="px-sprite">
          <Sprite
            mascot={pixie.mascot}
            color={pixie.color}
            size={16}
            working={running}
            phaseKey={pixie.id}
          />
        </span>
        <span className="px-label" ref={labelRef}>
          <span className="px-name">{pixie.name}</span>
          {leader && <span className="px-leader">Leader</span>}
          <span className={handleShown ? "px-slug" : "px-slug gone"}>{handle}</span>
        </span>
        <Trail waiting={waiting} running={running} />
      </button>
      <span className="px-racts">
        <RowActionsMenu title={pixie.name} items={items} onOpenChange={setMenuOpen} />
      </span>
      {context.menu}
    </div>
  );
}

/** What the row shows at its end while the pointer is not over it. */
function Trail({ waiting, running }: { waiting: number; running: boolean }): ReactNode {
  if (waiting > 0) {
    return (
      <span className="px-trail">
        <CountBadge count={waiting} urgent />
      </span>
    );
  }
  // The sprite beside it hops while the pixie works: a plain dot here.
  if (running) {
    return (
      <span className="px-trail">
        <StatusDot tone="run" />
      </span>
    );
  }
  return null;
}
