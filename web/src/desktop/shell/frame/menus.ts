// The frame's menus as the Mac lists them (ProjectHeader.swift's ProjectMenu, ChatRow.swift's
// ChatActions, ClaudeChatRow.swift's ClaudeChatActions, TabStrip.swift's AddProjectPopover),
// as entries for the desktop kit's Menu, so what each lists in each state is tested alone.
import type { RepoApp } from "../../../api/client.ts";
import type { ClaudeChat, RepoConfig, Session } from "../../../api/types.ts";
import { GENERAL } from "../../../store/general.ts";
import { separator, type MenuEntry } from "../../ui/menuItems.ts";

export interface ProjectMenuActions {
  newTerminal: () => void;
  newBrowser: () => void;
  openIn: (app: RepoApp) => void;
  copyPath: () => void;
  settings: () => void;
}

/**
 * The project name's menu. General's folder belongs to Nest: no terminal in it, no path to
 * copy and no settings (B110).
 */
export function projectMenu(
  project: string,
  vscodeShortcut: string,
  run: ProjectMenuActions,
): MenuEntry[] {
  const general = project === GENERAL;
  return [
    ...(general
      ? []
      : [{ title: "New terminal", icon: "terminal" as const, onSelect: run.newTerminal }]),
    { title: "New browser", icon: "globe", onSelect: run.newBrowser },
    separator,
    {
      title: "Open in VS Code",
      icon: "code",
      shortcut: vscodeShortcut,
      onSelect: () => {
        run.openIn("vscode");
      },
    },
    {
      title: "Show in Files",
      icon: "folder",
      onSelect: () => {
        run.openIn("finder");
      },
    },
    {
      title: "Open in Terminal",
      icon: "terminal",
      onSelect: () => {
        run.openIn("terminal");
      },
    },
    ...(general
      ? []
      : [
          separator,
          { title: "Copy path", icon: "copy" as const, onSelect: run.copyPath },
          separator,
          { title: "Project settings…", icon: "gear" as const, onSelect: run.settings },
        ]),
  ];
}

export interface ChatMenuActions {
  setPinned: (pinned: boolean) => void;
  setArchived: (archived: boolean) => void;
  rename: () => void;
  continueInClaudeCode: () => void;
  terminalHere: (folder: string) => void;
  delete: () => void;
}

/**
 * A Nest chat's "…" and right-click menu: pin (or unarchive), rename, continue in Claude
 * Code, a terminal where it works while it is not closed, archive, then delete.
 */
export function chatMenu(
  session: Session,
  folder: string | null,
  run: ChatMenuActions,
): MenuEntry[] {
  const archived = session.archived_at !== null;
  return [
    archived
      ? {
          title: "Unarchive",
          icon: "archive",
          onSelect: () => {
            run.setArchived(false);
          },
        }
      : {
          title: session.pinned ? "Unpin" : "Pin",
          icon: "pin",
          onSelect: () => {
            run.setPinned(!session.pinned);
          },
        },
    { title: "Rename", icon: "edit", onSelect: run.rename },
    { title: "Continue in Claude Code", icon: "terminal", onSelect: run.continueInClaudeCode },
    ...(folder !== null && session.state !== "closed"
      ? [
          {
            title: "Terminal here",
            icon: "terminal" as const,
            onSelect: () => {
              run.terminalHere(folder);
            },
          },
        ]
      : []),
    ...(archived
      ? []
      : [
          {
            title: "Archive",
            icon: "archive" as const,
            onSelect: () => {
              run.setArchived(true);
            },
          },
        ]),
    separator,
    { title: "Delete…", icon: "trash", danger: true, onSelect: run.delete },
  ];
}

export interface ClaudeChatMenuActions {
  open: () => void;
  continueInNest: () => void;
  setArchived: (archived: boolean) => void;
}

/** A Claude Code or Codex chat's menu: open, continue in Nest, archive or unarchive. */
export function claudeChatMenu(chat: ClaudeChat, run: ClaudeChatMenuActions): MenuEntry[] {
  return [
    { title: "Open", icon: "open", onSelect: run.open },
    { title: "Continue in Nest", icon: "spark", onSelect: run.continueInNest },
    separator,
    {
      title: chat.archived ? "Unarchive" : "Archive",
      icon: "archive",
      onSelect: () => {
        run.setArchived(!chat.archived);
      },
    },
  ];
}

/** The + popover's lists: General always, with whether it is open, then the closed projects. */
export function addProjectRows(
  open: string[],
  repos: RepoConfig[],
): { generalDetail: string; closed: RepoConfig[] } {
  return {
    generalDetail: open.includes(GENERAL) ? "Chats with no project, open" : "Chats with no project",
    closed: repos.filter((r) => r.name !== GENERAL && !open.includes(r.name)),
  };
}

/** A picked folder: the project already registered there, or a new one to register. */
export function folderChoice(
  path: string,
  repos: RepoConfig[],
): { open: string } | { register: string } {
  const folder = path.length > 1 ? path.replace(/\/+$/, "") : path;
  const known = repos.find((r) => r.path.replace(/\/+$/, "") === folder);
  return known === undefined ? { register: folder } : { open: known.name };
}
