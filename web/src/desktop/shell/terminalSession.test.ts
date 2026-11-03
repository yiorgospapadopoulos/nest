// A terminal pane talks to its shell: typing reaches it, a resize tells it the new size,
// and its end shows in the pane.
import { describe, expect, it, vi } from "vitest";
import { browserBridge, type Bridge, type PtyHandlers } from "../bridge.ts";
import {
  connectTerminal,
  TerminalSession,
  terminalKeys,
  type ScreenLike,
  type TerminalLike,
} from "./terminalSession.ts";
import { ToolSessions } from "./toolSessions.ts";

function fakeTerminal() {
  let onData: (data: string) => void = () => undefined;
  let onResize: (size: { cols: number; rows: number }) => void = () => undefined;
  const written: string[] = [];
  const terminal: TerminalLike = {
    cols: 80,
    rows: 24,
    write: (data) => {
      written.push(data);
    },
    onData: (listener) => {
      onData = listener;
      return { dispose: () => (onData = () => undefined) };
    },
    onResize: (listener) => {
      onResize = listener;
      return { dispose: () => (onResize = () => undefined) };
    },
  };
  return {
    terminal,
    written,
    type: (data: string) => {
      onData(data);
    },
    resize: (cols: number, rows: number) => {
      onResize({ cols, rows });
    },
  };
}

function fakeBridge() {
  const pty = { write: vi.fn(), resize: vi.fn(), kill: vi.fn() };
  let handlers: PtyHandlers | null = null;
  const spawnPty = vi.fn<Bridge["spawnPty"]>((_id, _options, given) => {
    handlers = given;
    return Promise.resolve(pty);
  });
  const bridge: Bridge = { ...browserBridge({ search: "" }, null), native: true, spawnPty };
  return { bridge, pty, spawnPty, handlers: () => handlers };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("a terminal pane's copy and paste keys", () => {
  const key = (type: string, init: KeyboardEventInit) =>
    new KeyboardEvent(type, { cancelable: true, ...init });

  it("pastes once on Ctrl+Shift+V: the web view's own paste of the press is cancelled", async () => {
    const paste = vi.fn();
    const handle = terminalKeys(
      { hasSelection: () => false, getSelection: () => "", paste },
      { writeText: () => Promise.resolve(), readText: () => Promise.resolve("ls -la") },
    );
    const down = key("keydown", { key: "V", ctrlKey: true, shiftKey: true });
    expect(handle(down)).toBe(false);
    expect(down.defaultPrevented).toBe(true);
    const press = key("keypress", { key: "V", ctrlKey: true, shiftKey: true });
    expect(handle(press)).toBe(false);
    expect(press.defaultPrevented).toBe(true);
    await settle();
    expect(paste).toHaveBeenCalledTimes(1);
    expect(paste).toHaveBeenCalledWith("ls -la");
  });

  it("copies the selection on Ctrl+Shift+C and leaves Ctrl+C and the window's keys alone", () => {
    const writeText = vi.fn(() => Promise.resolve());
    const handle = terminalKeys(
      { hasSelection: () => true, getSelection: () => "README.md", paste: vi.fn() },
      { writeText, readText: () => Promise.resolve("") },
    );
    expect(handle(key("keydown", { key: "C", ctrlKey: true, shiftKey: true }))).toBe(false);
    expect(writeText).toHaveBeenCalledWith("README.md");
    // Ctrl+C interrupts in the shell; Ctrl+Shift+T is the window's New terminal.
    expect(handle(key("keydown", { key: "c", ctrlKey: true }))).toBe(true);
    const window = key("keydown", { key: "T", ctrlKey: true, shiftKey: true });
    expect(handle(window)).toBe(false);
    expect(window.defaultPrevented).toBe(false);
  });
});

describe("a terminal pane", () => {
  it("starts the shell at the terminal's size in the pane's folder", async () => {
    const { terminal } = fakeTerminal();
    const { bridge, spawnPty } = fakeBridge();
    connectTerminal(terminal, bridge, "t-1", "/repo");
    await settle();
    expect(spawnPty).toHaveBeenCalledWith(
      "t-1",
      { cwd: "/repo", cols: 80, rows: 24 },
      expect.anything(),
    );
  });

  it("sends what is typed to the shell and its output to the terminal", async () => {
    const term = fakeTerminal();
    const { bridge, pty, handlers } = fakeBridge();
    connectTerminal(term.terminal, bridge, "t-1", "/repo");
    await settle();
    term.type("ls\r");
    expect(pty.write).toHaveBeenCalledWith("ls\r");
    handlers()?.onOutput("README.md\r\n");
    expect(term.written).toContain("README.md\r\n");
  });

  it("tells the shell its new columns and rows when the pane is resized", async () => {
    const term = fakeTerminal();
    const { bridge, pty } = fakeBridge();
    connectTerminal(term.terminal, bridge, "t-1", "/repo");
    await settle();
    term.resize(132, 40);
    expect(pty.resize).toHaveBeenCalledWith(132, 40);
  });

  it("shows when the shell ends, and that it could not start", async () => {
    const term = fakeTerminal();
    const { bridge, handlers } = fakeBridge();
    connectTerminal(term.terminal, bridge, "t-1", "/repo");
    await settle();
    handlers()?.onExit(130);
    expect(term.written.join("")).toContain("The shell ended (130).");

    const failing = fakeTerminal();
    const refused: Bridge = {
      ...bridge,
      spawnPty: () => Promise.reject(new Error("No such folder: /gone")),
    };
    connectTerminal(failing.terminal, refused, "t-2", "/gone");
    await settle();
    expect(failing.written.join("")).toContain("No such folder: /gone");
  });

  it("types Run in terminal's lines once the shell has started, and starts a new one after it ended", async () => {
    const term = fakeTerminal();
    const { bridge, pty, spawnPty, handlers } = fakeBridge();
    let type: (line: string) => void = () => undefined;
    const dropped = vi.fn();
    connectTerminal(term.terminal, bridge, "t-1", "/repo", {
      attach: (given) => {
        type = given;
        return () => undefined;
      },
      dropped,
    });
    type("npm test\n");
    expect(pty.write).not.toHaveBeenCalled();
    await settle();
    expect(pty.write).toHaveBeenCalledWith("npm test\n");
    handlers()?.onExit(0);
    type("ls\n");
    expect(spawnPty).toHaveBeenCalledTimes(2);
    await settle();
    expect(pty.write).toHaveBeenLastCalledWith("ls\n");
    expect(dropped).not.toHaveBeenCalled();
  });

  it("types nothing when the shell cannot start in its folder, and says so", async () => {
    const term = fakeTerminal();
    const { bridge } = fakeBridge();
    const refused: Bridge = {
      ...bridge,
      spawnPty: () => Promise.reject(new Error("No such folder: /gone")),
    };
    let type: (line: string) => void = () => undefined;
    const dropped = vi.fn();
    connectTerminal(term.terminal, refused, "t-1", "/gone", {
      attach: (given) => {
        type = given;
        return () => undefined;
      },
      dropped,
    });
    type("rm -r build\n");
    await settle();
    expect(dropped).toHaveBeenCalledWith(1);
    type("ls\n");
    expect(dropped).toHaveBeenCalledTimes(2);
  });

  it("ends the shell when the pane closes, even before it started", async () => {
    const term = fakeTerminal();
    const { bridge, pty } = fakeBridge();
    const end = connectTerminal(term.terminal, bridge, "t-1", "/repo");
    end();
    await settle();
    expect(pty.kill).toHaveBeenCalledTimes(1);
    term.type("x");
    expect(pty.write).not.toHaveBeenCalled();
  });
});

// Regression (production check, 2026-11-03): a terminal's shell ended, and what it showed
// was lost, on any switch to Board, Artifacts or another project. As the Mac's
// ToolSessions, it lives until its pane is closed or its project removed.
describe("a terminal pane's session", () => {
  function session(bridge: Bridge) {
    const term = fakeTerminal();
    const screen = { ...term.terminal, open: vi.fn(), dispose: vi.fn() };
    return {
      term,
      screen,
      made: new TerminalSession<ScreenLike>(
        screen,
        (s) => connectTerminal(s, bridge, "terminal-1", "/home/me/app"),
        document.createElement("div"),
      ),
    };
  }

  it("keeps its shell and screen while its view goes and comes back", async () => {
    const { bridge, pty, spawnPty, handlers } = fakeBridge();
    const sessions = new ToolSessions<TerminalSession>();
    const first = session(bridge);
    let makes = 0;
    const get = () =>
      sessions.session("terminal:1", () => {
        makes += 1;
        return first.made;
      });
    const pane = document.createElement("div");
    get().attach(pane);
    await settle();
    handlers()?.onOutput("$ make test\r\n");
    // Another tab: the view goes, and a new one shows the same screen.
    get().detach(pane);
    expect(pane.childElementCount).toBe(0);
    const again = document.createElement("div");
    get().attach(again);
    expect(again.firstElementChild).toBe(get().host);
    expect(spawnPty).toHaveBeenCalledTimes(1);
    expect(pty.kill).not.toHaveBeenCalled();
    expect(makes).toBe(1);
    expect(first.term.written).toContain("$ make test\r\n");
    expect(first.screen.open).toHaveBeenCalledTimes(1);
  });

  it("ends when its pane is closed or its project removed, and only then", async () => {
    const { bridge, pty } = fakeBridge();
    const sessions = new ToolSessions<TerminalSession>();
    const kept = session(bridge);
    const closed = session(bridge);
    sessions.session("terminal:kept", () => kept.made).attach(document.createElement("div"));
    sessions.session("terminal:closed", () => closed.made).attach(document.createElement("div"));
    await settle();
    sessions.keep(new Set(["terminal:kept"]));
    expect(pty.kill).toHaveBeenCalledTimes(1);
    expect(closed.screen.dispose).toHaveBeenCalledTimes(1);
    expect(kept.screen.dispose).not.toHaveBeenCalled();
    expect(sessions.find("terminal:kept")).toBe(kept.made);
    expect(sessions.find("terminal:closed")).toBeUndefined();
  });
});
