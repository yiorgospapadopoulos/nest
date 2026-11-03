// Ported from NestKitTests/ToolPaneTests.swift: tool panes follow the chat rules, a
// project's terminal is reused by folder, and commands reach a shell only as one line.
import { describe, expect, it } from "vitest";
import { ProjectState } from "./project.ts";
import { browserPane, terminalLine, terminalPane, toolTitle } from "./tools.ts";
import { paneKind } from "./workspace.ts";

const size = { width: 1000, height: 600 };

describe("tool panes", () => {
  it("tell their kind from their id, each with its own id", () => {
    const terminal = terminalPane("/repo");
    expect(paneKind(terminal.id)).toBe("terminal");
    expect(paneKind(browserPane().id)).toBe("browser");
    expect(paneKind("claude-code:abc")).toBe("chat");
    expect(paneKind("draft-1")).toBe("chat");
    expect(new Set([terminal.id, terminalPane("/repo").id]).size).toBe(2);
  });

  it("name the folder or the host", () => {
    expect(terminalPane("/repo/./app/../web/").folder).toBe("/repo/web");
    expect(toolTitle(terminalPane("/Users/me/todo-ui"))).toBe("todo-ui");
    expect(toolTitle(browserPane())).toBe("Browser");
    expect(toolTitle(browserPane("http://localhost:3000/about"))).toBe("localhost");
    expect(toolTitle(browserPane("not a url"))).toBe("Browser");
  });

  it("open like chats and keep to four panes, forgetting a replaced one", () => {
    const state = new ProjectState();
    state.view = "board";
    state.openChat("c1", size);
    const terminal = terminalPane("/repo");
    const browser = browserPane();
    state.openTool(terminal, size);
    expect(state.view).toBe("workspace");
    expect(state.layout.focused).toBe(terminal.id);
    state.openChat("c2", size);
    state.openTool(browser, size);
    state.openChat("c3", size);
    expect(state.layout.leaves).toEqual(["c1", "c2", terminal.id, "c3"]);
    expect(state.openTools).toEqual([terminal]);
    state.dropChat("c4", terminal.id, "left");
    expect(state.layout.leaves).toEqual(["c1", "c2", "c4", "c3"]);
    expect(state.tools.size).toBe(0);
  });

  it("stay when a draft becomes a chat", () => {
    const state = new ProjectState();
    const browser = browserPane();
    state.openChat("draft-1", size);
    state.openTool(browser, size);
    state.replaceChat("draft-1", "s1");
    expect(state.layout.leaves).toEqual(["s1", browser.id]);
    expect(state.selectedChat).toBe("s1");
  });

  it("reuse the terminal of a folder and open a new one for another", () => {
    const state = new ProjectState();
    state.openChat("c1", size);
    const first = state.terminal("/repo", size);
    expect(first.opened).toBe(true);
    state.focusPane("c1");
    state.view = "board";
    const again = state.terminal("/repo/", size);
    expect(again.opened).toBe(false);
    expect(again.pane).toEqual(first.pane);
    expect(state.layout.focused).toBe(first.pane.id);
    expect(state.view).toBe("workspace");
    expect(state.terminal("/wt/a", size).opened).toBe(true);
    // The status bar's Terminal takes whichever terminal is open.
    expect(state.projectTerminal("/elsewhere", size).opened).toBe(false);
  });

  it("place a run's output beside its chat and reuse it", () => {
    const state = new ProjectState();
    state.openChat("c1", size);
    const pane = state.runOutput("/repo", "c1", "c1", size);
    expect(state.layout.leaves).toEqual(["c1", pane.id]);
    expect(state.layout.focused).toBe("c1");
    expect(state.runOutput("/repo", "c1", "c1", size)).toEqual(pane);
  });

  it("marks only the chat in the one pane, after a draft became it in place of another", () => {
    const state = new ProjectState();
    state.openChat("readme", size);
    state.replaceChat("readme", "draft:1");
    state.replaceChat("draft:1", "test");
    expect(state.layout.leaves).toEqual(["test"]);
    expect(state.layout.rowState("test")).toBe("focused");
    expect(state.layout.rowState("readme")).toBe("closed");
  });

  it("close, and a closed selected chat hands the selection to the focus", () => {
    const state = new ProjectState();
    state.openChat("c1", size);
    state.openChat("c2", size);
    state.closePane("c2");
    expect(state.selectedChat).toBe("c1");
  });
});

describe("commands sent to a terminal", () => {
  it("run as one line with one newline", () => {
    expect(terminalLine("npm test")).toBe("npm test\n");
    expect(terminalLine("  make check\n\n")).toBe("make check\n");
    expect(terminalLine("printf\t'%s'")).toBe("printf\t'%s'\n");
  });

  it("are refused when they span lines or have nothing left", () => {
    for (const command of [
      "cd web\nnpm run dev",
      "ls\rrm -r build",
      "ls pwd",
      "ls\u000Bpwd",
      "ls\u0085pwd",
      "   ",
      "\u001B\u0007",
    ]) {
      expect(terminalLine(command)).toBeNull();
    }
  });

  it("lose control and direction characters", () => {
    expect(terminalLine("echo \u001B[2Jhi\u0007")).toBe("echo [2Jhi\n");
    expect(terminalLine("rm\u0000 x\u007F\u009B")).toBe("rm x\n");
    expect(terminalLine("cat ‮txt.exe‬")).toBe("cat txt.exe\n");
    expect(terminalLine("echo 👩‍💻")).toBe("echo 👩‍💻\n");
  });
});
