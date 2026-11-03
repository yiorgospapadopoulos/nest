// Where a terminal opens for a pane (B60), ported from NestKit's TerminalFolder.swift: the
// status bar's Terminal button follows the focused chat; New terminal always opens one more.
import type { ClaudeChat, RepoConfig, Session } from "../../../api/types.ts";
import { repoNamed } from "../../../store/general.ts";
import { terminalLine } from "../../layout/tools.ts";
import type { Shell } from "../context.ts";
import { typeLine } from "../terminalLines.ts";

export const GONE_MESSAGE = "This chat's folder no longer exists, so nothing was run there.";

// A Claude Code chat's pane id (shell/panes.ts).
const CLAUDE = "claude-code:";

export interface FolderData {
  sessions: Record<string, Session>;
  claudeChats: Record<string, ClaudeChat>;
  repos: RepoConfig[];
}

export type TerminalTarget =
  // The focused chat's folder: the terminal pane there, or a new one.
  | { kind: "chat"; folder: string }
  // No chat is focused: the project's terminal pane, or a new one in the project folder.
  | { kind: "project"; folder: string }
  // The focused chat's folder is gone (GONE_MESSAGE).
  | { kind: "gone"; folder: string };

/**
 * The folder a pane's chat works in: its worktree, its folder in place (else its
 * project's), or a Claude Code chat's folder. Null for a new chat and tool panes.
 */
export function paneFolder(pane: string, data: FolderData): string | null {
  if (pane.startsWith(CLAUDE)) return data.claudeChats[pane.slice(CLAUDE.length)]?.cwd ?? null;
  const session = data.sessions[pane];
  if (session === undefined) return null;
  return session.worktree_path ?? session.cwd ?? repoNamed(data.repos, session.repo)?.path ?? null;
}

/**
 * Whether a chat's folder is still there. The disk is the daemon's, so this asks the
 * chats: a closed worktree chat's worktree was removed with its merge or discard.
 */
export function folderExists(data: FolderData): (folder: string) => boolean {
  const gone = new Set(
    Object.values(data.sessions).flatMap((s) =>
      s.state === "closed" && s.mode === "worktree" && s.worktree_path !== null
        ? [s.worktree_path]
        : [],
    ),
  );
  return (folder) => !gone.has(folder);
}

/**
 * Where the Terminal button opens a shell: the folder of the focused chat pane, else the
 * project's folder, which opens without asking whether it exists. Null without either.
 */
export function terminalButtonTarget(
  focused: string | null,
  project: string | null,
  data: FolderData,
  exists: (folder: string) => boolean = folderExists(data),
): TerminalTarget | null {
  const folder = focused === null ? null : paneFolder(focused, data);
  if (folder !== null) return exists(folder) ? { kind: "chat", folder } : { kind: "gone", folder };
  const repo = project === null ? undefined : repoNamed(data.repos, project);
  // General's folder belongs to Nest, so it has no terminal of its own (B110).
  return repo === undefined || repo.path === "" ? null : { kind: "project", folder: repo.path };
}

/**
 * Run in terminal on a command from a chat, as the Mac's runInTerminal: the line, cleaned
 * as `terminalLine` cleans it, typed into the terminal pane in the chat's folder (an open
 * one, else a new one), or in the project's folder without a chat. It runs without asking:
 * the user clicked Run in terminal. Nothing runs for a command of several lines, nor in a
 * folder that is gone.
 */
export function runInTerminal(
  shell: Shell,
  data: FolderData,
  command: string,
  pane: string | null,
  toast: (text: string) => void,
  type: (pane: string, line: string) => void = typeLine,
): void {
  if (shell.project === null) return;
  const line = terminalLine(command);
  if (line === null) return;
  const folder =
    (pane === null ? null : paneFolder(pane, data)) ??
    repoNamed(data.repos, shell.project)?.path ??
    null;
  if (folder === null) return;
  if (!folderExists(data)(folder)) {
    toast(GONE_MESSAGE);
    return;
  }
  const size = shell.workspaceSize();
  // Worked out on a copy first, so the pane's id is known before the change applies.
  const target = shell.state.copy().terminal(folder, size).pane;
  shell.update((s) => {
    if (s.openTools.some((p) => p.id === target.id)) s.terminal(folder, size);
    else s.openTool(target, size);
  });
  type(target.id, line);
}

/**
 * The Terminal button (B60), as the Mac's openProjectTerminal: the terminal pane in the
 * focused chat's folder, or a new one there; without a focused chat, the project's terminal
 * pane, or a new one in the project folder. Nothing opens for a chat whose folder is gone.
 */
export function openProjectTerminal(
  shell: Shell,
  data: FolderData,
  toast: (text: string) => void,
): void {
  const target = terminalButtonTarget(shell.state.layout.focused, shell.project, data);
  if (target === null) return;
  if (target.kind === "gone") {
    toast(GONE_MESSAGE);
    return;
  }
  shell.update((s) => {
    if (target.kind === "chat") s.terminal(target.folder, shell.workspaceSize());
    else s.projectTerminal(target.folder, shell.workspaceSize());
  });
}
