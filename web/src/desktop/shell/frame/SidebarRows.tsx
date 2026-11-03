import type { CSSProperties, DragEvent, ReactNode } from "react";
import type { ClaudeChat, Session } from "../../../api/types.ts";
import {
  claudeChatPlace,
  placeName,
  sessionPlace,
  type ChatPlace,
} from "../../../screens/chat/place.ts";
import { useStore } from "../../../store/context.ts";
import { repoNamed } from "../../../store/general.ts";
import type { ChatStatus } from "../../../store/selectors.ts";
import { Icon } from "../../../ui/Icon.tsx";
import type { LoadedMap } from "../../chat/branchMaps.ts";
import { Sprite } from "../../pixies/Sprite.tsx";
import { useContextMenu } from "../../ui/contextMenu.tsx";
import { Menu } from "../../ui/Menu.tsx";
import type { MenuEntry } from "../../ui/menuItems.ts";
import { RenameField } from "../../ui/RenameField.tsx";
import { ForkIcon, PANE_DRAG } from "../bits.tsx";
import { useShell } from "../context.ts";
import { claudePane } from "../panes.ts";
import { useTap } from "../tap.ts";
import { placeColor } from "./projectMap.ts";
import { endRename, useRenaming } from "./rename.ts";

// The open menu is drawn elsewhere but its events still reach the row that opened it.
const inMenu = (target: EventTarget) =>
  target instanceof Element && target.closest("[data-dk-menu]") !== null;

/** The colour of the branch a chat works on and where that is, for its second line. */
function PlaceMark({ place, map }: { place: ChatPlace; map: LoadedMap | null }) {
  const color = placeColor(map, place);
  const name = placeName(place);
  return (
    <span
      className="fr-place"
      style={color === null ? undefined : ({ "--lane": color } as CSSProperties)}
      title={place.kind === "worktree" ? `Worktree ${name}` : `On ${name} in the project folder`}
    >
      <ForkIcon />
      <span>{name}</span>
    </span>
  );
}

/** The row's "…" button, shown on hover, opening the same menu as a right click. */
function More({ title, items }: { title: string; items: () => MenuEntry[] }) {
  return (
    <Menu label={`Actions for ${title}`} items={items} align="end">
      {(trigger, open) => (
        <button
          {...trigger}
          className={open ? "fr-more on" : "fr-more"}
          title="More"
          aria-label={`Actions for ${title}`}
        >
          <Icon name="dots" />
        </button>
      )}
    </Menu>
  );
}

interface FrameProps {
  pane: string;
  title: string;
  label: string;
  tone: string;
  items: () => MenuEntry[];
  // The second line: where it works and its marks; nothing when it has none.
  line: ReactNode;
  finished?: boolean;
}

/**
 * A chat's row, as the Mac's ChatRow: status dot and title over its second line, filled
 * while its pane has the focus, faintly while open in another (B93). A click opens it, it
 * drags onto the workspace, a right click opens its menu at the pointer and on hover a
 * "…" opens it below.
 */
function RowFrame({ pane, title, label, tone, items, line, finished = false }: FrameProps) {
  const shell = useShell();
  const rowState = shell.state.layout.rowState(pane);
  const context = useContextMenu(`Actions for ${title}`, items);
  const tap = useTap(() => {
    shell.openPane(pane);
  });
  const onDragStart = (event: DragEvent<HTMLButtonElement>) => {
    event.dataTransfer.setData(PANE_DRAG, pane);
    event.dataTransfer.effectAllowed = "move";
  };
  return (
    <div
      className={context.open ? "fr-row dk-hrow menu" : "fr-row dk-hrow"}
      onContextMenu={(event) => {
        if (!inMenu(event.target)) context.onContextMenu(event);
      }}
    >
      <button
        className={`dk-row ${rowState}${finished && rowState !== "focused" ? " finished" : ""}`}
        data-chat={pane}
        draggable
        onDragStart={onDragStart}
        aria-label={label}
        aria-current={rowState === "focused" ? "true" : undefined}
        {...tap}
      >
        <span className={`dot s-${tone}`} aria-hidden="true" />
        <span className="dk-rbody">
          <span className="dk-rt">{title}</span>
          {line}
        </span>
      </button>
      <span className="dk-hacts" data-revealed={context.open || undefined}>
        <More title={title} items={items} />
      </span>
      {context.menu}
    </div>
  );
}

/** The inline name field in the row's place, as the Mac's renameField. */
function RenameRow({ session }: { session: Session }) {
  const { actions } = useStore();
  return (
    <div className="fr-renamerow">
      <RenameField
        value={session.title}
        label="Rename chat"
        onCommit={(name) => {
          endRename();
          void actions.update(session.id, { title: name });
        }}
        onCancel={endRename}
      />
    </div>
  );
}

interface ChatRowProps {
  session: Session;
  status: ChatStatus;
  map: LoadedMap | null;
  items: () => MenuEntry[];
}

export function ChatRow({ session, status, map, items }: ChatRowProps) {
  const { state } = useStore();
  const renaming = useRenaming();
  if (renaming === session.id) return <RenameRow session={session} />;
  const repo = repoNamed(state.repos, session.repo);
  const place = sessionPlace(session, repo);
  const starter = session.started_by_pixie;
  const pixie = starter === null ? undefined : state.pixies[starter];
  const startedBy = starter === null ? null : `Started by ${pixie?.name ?? "a pixie"}`;
  const marks =
    place !== null || session.issue !== null || session.pinned || session.stuck !== null;
  const label = [
    session.title,
    status.label,
    place === null
      ? null
      : place.kind === "worktree"
        ? `worktree ${placeName(place)}`
        : `on ${placeName(place)}`,
    session.issue === null ? null : `issue #${String(session.issue.number)}`,
    session.stuck === null ? null : "stuck",
    startedBy,
    session.pinned ? "pinned" : null,
  ]
    .filter(Boolean)
    .join(", ");
  return (
    <RowFrame
      pane={session.id}
      title={session.title}
      label={label}
      tone={status.tone}
      items={items}
      finished={session.state === "closed"}
      line={
        (marks || startedBy !== null) && (
          <span className="dk-rb">
            {place !== null && <PlaceMark place={place} map={map} />}
            {session.issue !== null && (
              <>
                {place !== null && <span>·</span>}
                <span className="fr-num">#{session.issue.number}</span>
              </>
            )}
            {session.pinned && <Icon name="pin" className="dk-pin" />}
            {session.stuck !== null && (
              <>
                {(place !== null || session.pinned) && <span>·</span>}
                <span className="fr-stuck" title={session.stuck.details}>
                  Stuck
                </span>
              </>
            )}
            {startedBy !== null && (
              <span className="fr-starter" title={startedBy}>
                {pixie === undefined ? (
                  <Icon name="spark" />
                ) : (
                  <Sprite mascot={pixie.mascot} color={pixie.color} size={11} />
                )}
              </span>
            )}
          </span>
        )
      }
    />
  );
}

interface ClaudeRowProps {
  chat: ClaudeChat;
  map: LoadedMap | null;
  items: () => MenuEntry[];
}

const ENGINES: Record<string, string> = { claude: "Claude Code", codex: "Codex" };

/** A Claude Code or Codex chat Nest does not own, as the Mac's ClaudeChatRow. */
export function ClaudeChatRow({ chat, map, items }: ClaudeRowProps) {
  const { state } = useStore();
  const repo = repoNamed(state.repos, chat.repo);
  const place = claudeChatPlace(chat, repo);
  const engine = ENGINES[chat.engine ?? "claude"] ?? "Claude Code";
  const open = chat.open_in_claude_code;
  return (
    <RowFrame
      pane={claudePane(chat.id)}
      title={chat.title}
      label={[
        chat.title,
        `${engine} chat`,
        place === null ? null : placeName(place),
        open ? "open in Claude Code" : null,
      ]
        .filter(Boolean)
        .join(", ")}
      tone="done"
      items={items}
      line={
        (place !== null || open) && (
          <span className="dk-rb">
            {place !== null && <PlaceMark place={place} map={map} />}
            {open && (
              <>
                {place !== null && <span>·</span>}
                <span>open there</span>
              </>
            )}
          </span>
        )
      }
    />
  );
}

/**
 * A chat in the squeezed sidebar: its status dot, its title on hover, its menu on a right
 * click; it drags, and a click opens the sidebar, as the rest of the rail does.
 */
export function RailDot({
  pane,
  title,
  tone,
  open,
  items,
}: {
  pane: string;
  title: string;
  tone: string;
  open: boolean;
  items: () => MenuEntry[];
}) {
  const context = useContextMenu(`Actions for ${title}`, items);
  return (
    <span
      className={open ? "dk-rdot open" : "dk-rdot"}
      title={title}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData(PANE_DRAG, pane);
        event.dataTransfer.effectAllowed = "move";
      }}
      onContextMenu={(event) => {
        if (!inMenu(event.target)) context.onContextMenu(event);
      }}
    >
      <span className={`dot s-${tone}`} />
      {context.menu}
    </span>
  );
}
