// Ported from NestKitTests' TerminalFolderTests (B60, audit BUG-55, BUG-56).
import { describe, expect, it } from "vitest";
import { GENERAL } from "../../../store/general.ts";
import { claudeChat, repo, session } from "../../../test/fixtures.ts";
import { ProjectState } from "../../layout/project.ts";
import type { Shell } from "../context.ts";
import {
  folderExists,
  GONE_MESSAGE,
  paneFolder,
  runInTerminal,
  terminalButtonTarget,
  type FolderData,
} from "./terminal.ts";

const chat = claudeChat({ id: "c1", cwd: "/Users/me/todo-ui/.claude/worktrees/hero" });
const data: FolderData = {
  sessions: {
    wt: session({ id: "wt", worktree_path: "/w/wt", cwd: "/w/wt" }),
    ip: session({ id: "ip", repo: "map-viewer", mode: "in_place", worktree_path: null, cwd: null }),
    merged: session({ id: "merged", worktree_path: "/w/merged", state: "closed" }),
  },
  claudeChats: { c1: chat },
  repos: [repo("todo-ui"), repo("map-viewer")],
};
const project = "/Users/me/todo-ui";

describe("a pane's folder", () => {
  it("is its chat's worktree, its project's folder in place, or a Claude Code chat's", () => {
    expect(paneFolder("wt", data)).toBe("/w/wt");
    expect(paneFolder("ip", data)).toBe("/Users/me/map-viewer");
    expect(paneFolder("claude-code:c1", data)).toBe(chat.cwd);
    expect(paneFolder("draft:1-1", data)).toBeNull();
    expect(paneFolder("terminal-1", data)).toBeNull();
  });
});

describe("the Terminal button", () => {
  const existing = new Set(["/w/wt", chat.cwd]);
  const target = (pane: string | null, name: string | null) =>
    terminalButtonTarget(pane, name, data, (folder) => existing.has(folder));

  it("opens where the focused chat works, else the project's terminal", () => {
    expect(target("wt", "todo-ui")).toEqual({ kind: "chat", folder: "/w/wt" });
    expect(target("claude-code:c1", "todo-ui")).toEqual({ kind: "chat", folder: chat.cwd });
    // A new chat, a tool pane or no focus: the project's terminal, without asking the disk.
    expect(target("draft:1-1", "todo-ui")).toEqual({ kind: "project", folder: project });
    expect(target("terminal-1", "todo-ui")).toEqual({ kind: "project", folder: project });
    expect(target(null, "todo-ui")).toEqual({ kind: "project", folder: project });
    expect(target("wt", null)).toEqual({ kind: "chat", folder: "/w/wt" });
    expect(target(null, null)).toBeNull();
    expect(target(null, "no-such-project")).toBeNull();
  });

  // Regression (VM, 2026-11-03): in General a terminal opened titled "." in the home
  // folder. General's folder belongs to Nest; only a focused General chat's folder opens.
  it("opens no project terminal in General", () => {
    expect(target(null, GENERAL)).toBeNull();
    expect(target("wt", GENERAL)).toEqual({ kind: "chat", folder: "/w/wt" });
  });

  it("opens nothing in a merged chat's removed worktree", () => {
    expect(target("ip", "todo-ui")).toEqual({ kind: "gone", folder: "/Users/me/map-viewer" });
    // By default the chats tell: a closed worktree chat's folder went with it.
    expect(terminalButtonTarget("merged", "todo-ui", data)).toEqual({
      kind: "gone",
      folder: "/w/merged",
    });
    expect(terminalButtonTarget("wt", "todo-ui", data)).toEqual({ kind: "chat", folder: "/w/wt" });
    expect(folderExists(data)(project)).toBe(true);
  });
});

describe("Run in terminal on a command from a chat", () => {
  function fakeShell(name: string | null = "todo-ui") {
    let state = new ProjectState();
    const shell = {
      project: name,
      get state() {
        return state;
      },
      update: (change: (s: ProjectState) => void) => {
        const next = state.copy();
        change(next);
        state = next;
      },
      workspaceSize: () => ({ width: 1200, height: 800 }),
    } as unknown as Shell;
    const typed: [string, string][] = [];
    const toasts: string[] = [];
    const run = (command: string, pane: string | null) => {
      runInTerminal(
        shell,
        data,
        command,
        pane,
        (text) => toasts.push(text),
        (id, line) => typed.push([id, line]),
      );
    };
    const terminals = () => shell.state.openTools.filter((p) => p.kind === "terminal");
    return { run, typed, toasts, terminals };
  }

  it("types the cleaned line into a terminal in the chat's folder, the same one each time", () => {
    const { run, typed, terminals } = fakeShell();
    run("  npm\u0007 test\n", "wt");
    run("make check", "wt");
    expect(terminals().map((p) => p.folder)).toEqual(["/w/wt"]);
    const id = terminals()[0]?.id;
    expect(typed).toEqual([
      [id, "npm test\n"],
      [id, "make check\n"],
    ]);
  });

  it("runs in the project's folder without a chat's", () => {
    const { run, terminals } = fakeShell();
    run("ls", "draft:1-1");
    expect(terminals().map((p) => p.folder)).toEqual([project]);
  });

  it("runs nothing for a command of several lines, nor outside a project", () => {
    const several = fakeShell();
    several.run("cd web\nnpm run dev", "wt");
    several.run("ls pwd", "wt");
    expect(several.terminals()).toEqual([]);
    expect(several.typed).toEqual([]);
    const pixies = fakeShell(null);
    pixies.run("ls", "wt");
    expect(pixies.typed).toEqual([]);
  });

  it("opens nothing and says so when the chat's folder is gone", () => {
    const { run, typed, toasts, terminals } = fakeShell();
    run("ls", "merged");
    expect(terminals()).toEqual([]);
    expect(typed).toEqual([]);
    expect(toasts).toEqual([GONE_MESSAGE]);
  });
});
