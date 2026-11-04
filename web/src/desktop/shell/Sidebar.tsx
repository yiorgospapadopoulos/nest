import { Fragment, useState, type PointerEvent } from "react";
import type { Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { chatList, type ChatEntry } from "../../store/selectors.ts";
import { Icon } from "../../ui/Icon.tsx";
import { useKeysText } from "../layout/useShortcuts.ts";
import { RAIL_WIDTH } from "../layout/sidebar.ts";
import { useShell } from "./context.ts";
import { ChatTree } from "./frame/ChatTree.tsx";
import { Confirm } from "../sheets/Alert.tsx";
import "./frame/frame.css";
import { useChatMenus } from "./frame/chatMenus.ts";
import { ProjectHeader } from "./frame/ProjectHeader.tsx";
import { useProjectMap } from "./frame/projectMap.ts";
import { ChatRow, ClaudeChatRow, RailDot } from "./frame/SidebarRows.tsx";
import { agentPane, claudePane, workPane } from "./panes.ts";
import { UpdateRailDot, UpdateStrip } from "./UpdateStrip.tsx";

// Archived stays open per project while the app runs, as the Mac's archivedOpen.
const archivedOpen = new Set<string>();

/**
 * The project's chats, as the Mac's sidebar: the project and its branch (with the branch
 * map under it while open), New chat, then Pinned, the chats with their pixie and subagent
 * trees, and the folded Archived. Collapsed, it is a rail of status dots that opens it.
 */
export function Sidebar() {
  const shell = useShell();
  const map = useProjectMap();
  const keysOf = useKeysText();
  const [deleting, setDeleting] = useState<Session | null>(null);
  const menus = useChatMenus(setDeleting);
  return (
    <>
      {shell.state.leftCollapsed ? (
        <Rail menus={menus} />
      ) : (
        <aside
          className="dk-side fr-side"
          style={{ width: shell.desk.sidebarWidth }}
          aria-label="Chats"
        >
          <ProjectHeader map={map} />
          <button
            className="dk-act"
            title={`New chat (${keysOf("newChat")})`}
            onClick={shell.newChat}
          >
            <Icon name="plus" />
            New chat
          </button>
          <ChatGroups map={map} menus={menus} />
          <UpdateStrip />
          <ResizeHandle />
        </aside>
      )}
      {deleting !== null && (
        <DeleteChat
          session={deleting}
          onDone={() => {
            setDeleting(null);
          }}
        />
      )}
    </>
  );
}

type Menus = ReturnType<typeof useChatMenus>;

function DeleteChat({ session, onDone }: { session: Session; onDone: () => void }) {
  const { actions } = useStore();
  const shell = useShell();
  return (
    <Confirm
      title="Delete this chat?"
      message={`${session.title} is removed, with its pane, worktree and approvals.`}
      action="Delete"
      destructive
      onClose={onDone}
      onConfirm={() => {
        void actions.remove(session).then((removed) => {
          if (removed) shell.closePane(session.id);
        });
      }}
    />
  );
}

function ChatGroups({ map, menus }: { map: ReturnType<typeof useProjectMap>; menus: Menus }) {
  const { state } = useStore();
  const shell = useShell();
  const project = shell.repo.name;
  const [archived, setArchived] = useState(() => archivedOpen.has(project));
  const lists = chatList(state, project);

  const row = (entry: ChatEntry, inArchive: boolean) =>
    entry.session === undefined ? (
      <ClaudeChatRow
        key={`cc-${entry.chat.id}`}
        chat={entry.chat}
        map={map}
        items={() => menus.claude(entry.chat)}
      />
    ) : (
      <Fragment key={entry.session.id}>
        <ChatRow
          session={entry.session}
          status={entry.status}
          map={map}
          items={() => menus.session(entry.session)}
        />
        {/* Its pixies and running subagents, joined to it by tree lines (B46). */}
        {!inArchive && (
          <ChatTree
            session={entry.session}
            onOpenAgent={(call) => {
              shell.openPane(agentPane(entry.session.id, call));
            }}
            onOpenWork={(who) => {
              shell.openPane(workPane(entry.session.id, who));
            }}
          />
        )}
      </Fragment>
    );

  const empty = lists.pinned.length + lists.chats.length + lists.archived.length === 0;
  const pinned = lists.pinned.length > 0;
  return (
    <div className="dk-scroll">
      {empty && <p className="dk-empty">No chats yet</p>}
      {pinned && (
        <section aria-label="Pinned">
          <h2 className="dk-h fr-h">
            Pinned<span>{lists.pinned.length}</span>
          </h2>
          {lists.pinned.map((entry) => row(entry, false))}
        </section>
      )}
      {lists.chats.length > 0 && (
        <section aria-label="Chats">
          {/* The only list is untitled while nothing is pinned (B77). */}
          {pinned ? (
            <h2 className="dk-h fr-h">
              Chats<span>{lists.chats.length}</span>
            </h2>
          ) : (
            <div className="fr-gap" />
          )}
          {lists.chats.map((entry) => row(entry, false))}
        </section>
      )}
      {lists.archived.length > 0 && (
        <section aria-label="Archived">
          <button
            className="dk-h dk-fold fr-h"
            aria-expanded={archived}
            aria-label={`Archived, ${String(lists.archived.length)}`}
            onClick={() => {
              if (archived) archivedOpen.delete(project);
              else archivedOpen.add(project);
              setArchived(!archived);
            }}
          >
            <Icon name="chevr" />
            Archived<span>{lists.archived.length}</span>
          </button>
          {archived && lists.archived.map((entry) => row(entry, true))}
        </section>
      )}
    </div>
  );
}

/**
 * The squeezed sidebar: one status dot per chat (B83). A click anywhere on the strip, a dot
 * included, opens the sidebar; a dot shows its chat's title on hover, drags, and has the
 * chat's menu.
 */
function Rail({ menus }: { menus: Menus }) {
  const { state } = useStore();
  const shell = useShell();
  const lists = chatList(state, shell.repo.name);
  return (
    <div
      className="dk-rail"
      role="button"
      tabIndex={0}
      style={{ width: RAIL_WIDTH }}
      aria-label="Open sidebar"
      title="Open sidebar"
      onClick={shell.toggleSidebar}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          shell.toggleSidebar();
        }
      }}
    >
      {[...lists.pinned, ...lists.chats].map((entry) => {
        const pane = entry.session?.id ?? claudePane(entry.chat?.id ?? "");
        return (
          <RailDot
            key={pane}
            pane={pane}
            title={entry.session?.title ?? entry.chat?.title ?? ""}
            tone={entry.status.tone}
            open={shell.state.layout.contains(pane)}
            items={() =>
              entry.session !== undefined ? menus.session(entry.session) : menus.claude(entry.chat)
            }
          />
        );
      })}
      <UpdateRailDot />
    </div>
  );
}

/** The sidebar's right edge, dragged to set its width (B45). */
export function ResizeHandle() {
  const shell = useShell();
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const startX = event.clientX;
    const startWidth = shell.desk.sidebarWidth;
    const target = event.currentTarget;
    target.setPointerCapture(event.pointerId);
    const move = (e: globalThis.PointerEvent) => {
      shell.setSidebarWidth(startWidth + e.clientX - startX);
    };
    const up = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
  };
  return (
    <div
      className="dk-resize"
      role="separator"
      aria-orientation="vertical"
      aria-label="Sidebar width"
      onPointerDown={onPointerDown}
    />
  );
}
