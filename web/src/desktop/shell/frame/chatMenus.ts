import type { ClaudeChat, Session } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { useApi } from "../../context.ts";
import type { MenuEntry } from "../../ui/menuItems.ts";
import { useShell } from "../context.ts";
import { claudePane } from "../panes.ts";
import { chatMenu, claudeChatMenu } from "./menus.ts";
import { beginRename } from "./rename.ts";
import { folderExists, GONE_MESSAGE, paneFolder } from "./terminal.ts";

/** The actions of a Nest chat's and a Claude Code chat's menus, as the Mac's Shell has them. */
export function useChatMenus(onDelete: (session: Session) => void) {
  const { state, actions } = useStore();
  const shell = useShell();
  const api = useApi();
  const data = { sessions: state.sessions, claudeChats: state.claudeChats, repos: state.repos };
  const session = (chat: Session): MenuEntry[] =>
    chatMenu(chat, paneFolder(chat.id, data), {
      setPinned: (pinned) => {
        void actions.update(chat.id, { pinned });
      },
      setArchived: (archived) => {
        if (archived) shell.closePane(chat.id);
        void actions.update(chat.id, { archived });
      },
      rename: () => {
        if (shell.state.leftCollapsed) shell.toggleSidebar();
        beginRename(chat.id);
      },
      continueInClaudeCode: () => {
        api.openInClaudeCode(chat.id).then(
          (launch) => {
            actions.toast(launch.warning ?? "Opened in Terminal", launch.warning ? "info" : "ok");
          },
          (error: unknown) => {
            actions.toast(
              error instanceof Error ? error.message : "Could not open Claude Code",
              "error",
            );
          },
        );
      },
      terminalHere: (folder) => {
        if (!folderExists(data)(folder)) {
          actions.toast(GONE_MESSAGE, "error");
          return;
        }
        shell.update((s) => s.terminal(folder, shell.workspaceSize()));
      },
      delete: () => {
        onDelete(chat);
      },
    });
  const claude = (chat: ClaudeChat): MenuEntry[] =>
    claudeChatMenu(chat, {
      open: () => {
        shell.openPane(claudePane(chat.id));
      },
      continueInNest: () => {
        void actions.adoptClaudeChat(chat).then((made) => {
          if (made !== null) shell.replacePane(claudePane(chat.id), made.id);
        });
      },
      setArchived: (archived) => {
        if (archived) shell.closePane(claudePane(chat.id));
        void actions.archiveClaudeChat(chat, archived);
      },
    });
  return { session, claude };
}
