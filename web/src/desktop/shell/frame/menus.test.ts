// The frame's menus list what the Mac's do, in each state (ProjectHeader.swift, ChatRow.swift,
// ClaudeChatRow.swift, TabStrip.swift).
import { describe, expect, it, vi } from "vitest";
import { claudeChat, repo, session } from "../../../test/fixtures.ts";
import type { MenuEntry } from "../../ui/menuItems.ts";
import {
  addProjectRows,
  chatMenu,
  claudeChatMenu,
  folderChoice,
  projectMenu,
  type ChatMenuActions,
} from "./menus.ts";

const titles = (entries: MenuEntry[]) =>
  entries.map((e) => (e.type === "separator" ? "---" : "title" in e ? e.title : e.text));

const choose = (entries: MenuEntry[], title: string) => {
  const entry = entries.find((e) => "title" in e && e.title === title);
  if (entry === undefined || !("onSelect" in entry)) throw new Error(`no ${title}`);
  entry.onSelect();
};

describe("the project menu", () => {
  const run = {
    newTerminal: vi.fn(),
    newBrowser: vi.fn(),
    openIn: vi.fn(),
    copyPath: vi.fn(),
    settings: vi.fn(),
  };

  it("has the terminal, the folder's apps, Copy path and Project settings", () => {
    const entries = projectMenu("todo-ui", "Ctrl+Shift+O", run);
    expect(titles(entries)).toEqual([
      "New terminal",
      "New browser",
      "---",
      "Open in VS Code",
      "Show in Files",
      "Open in Terminal",
      "---",
      "Copy path",
      "---",
      "Project settings…",
    ]);
    choose(entries, "Project settings…");
    expect(run.settings).toHaveBeenCalled();
    choose(entries, "Show in Files");
    expect(run.openIn).toHaveBeenCalledWith("finder");
  });

  it("offers General no terminal, no path and no settings (B110)", () => {
    expect(titles(projectMenu("general", "", run))).toEqual([
      "New browser",
      "---",
      "Open in VS Code",
      "Show in Files",
      "Open in Terminal",
    ]);
  });
});

describe("a chat's menu", () => {
  const run = (): ChatMenuActions => ({
    setPinned: vi.fn(),
    setArchived: vi.fn(),
    rename: vi.fn(),
    continueInClaudeCode: vi.fn(),
    terminalHere: vi.fn(),
    delete: vi.fn(),
  });

  it("pins, renames, continues in Claude Code, opens a terminal there, archives, deletes", () => {
    const actions = run();
    const entries = chatMenu(session(), "/w/s1", actions);
    expect(titles(entries)).toEqual([
      "Pin",
      "Rename",
      "Continue in Claude Code",
      "Terminal here",
      "Archive",
      "---",
      "Delete…",
    ]);
    choose(entries, "Terminal here");
    expect(actions.terminalHere).toHaveBeenCalledWith("/w/s1");
    choose(entries, "Pin");
    expect(actions.setPinned).toHaveBeenCalledWith(true);
    expect(titles(chatMenu(session({ pinned: true }), null, actions))[0]).toBe("Unpin");
  });

  it("offers an archived chat Unarchive instead of Pin and Archive", () => {
    const actions = run();
    const entries = chatMenu(session({ archived_at: "2026-10-01T10:00:00Z" }), "/w/s1", actions);
    expect(titles(entries)).toEqual([
      "Unarchive",
      "Rename",
      "Continue in Claude Code",
      "Terminal here",
      "---",
      "Delete…",
    ]);
    choose(entries, "Unarchive");
    expect(actions.setArchived).toHaveBeenCalledWith(false);
  });

  it("has no terminal for a closed chat", () => {
    expect(titles(chatMenu(session({ state: "closed" }), "/w/s1", run()))).not.toContain(
      "Terminal here",
    );
  });

  it("opens, continues in Nest and archives a Claude Code chat", () => {
    const archive = vi.fn();
    const live = claudeChatMenu(claudeChat(), {
      open: vi.fn(),
      continueInNest: vi.fn(),
      setArchived: archive,
    });
    expect(titles(live)).toEqual(["Open", "Continue in Nest", "---", "Archive"]);
    choose(live, "Archive");
    expect(archive).toHaveBeenCalledWith(true);
    const archived = claudeChatMenu(claudeChat({ archived: true }), {
      open: vi.fn(),
      continueInNest: vi.fn(),
      setArchived: archive,
    });
    expect(titles(archived).at(-1)).toBe("Unarchive");
  });
});

describe("the + popover", () => {
  const repos = [repo("todo-ui"), repo("map-viewer"), repo("nest")];

  it("lists General, then the projects not open", () => {
    const rows = addProjectRows(["todo-ui"], repos);
    expect(rows.generalDetail).toBe("Chats with no project");
    expect(rows.closed.map((r) => r.name)).toEqual(["map-viewer", "nest"]);
    expect(addProjectRows(["general", "nest"], repos).generalDetail).toBe(
      "Chats with no project, open",
    );
  });

  it("opens a picked folder's project when it is registered, else registers it", () => {
    expect(folderChoice("/Users/me/nest/", repos)).toEqual({ open: "nest" });
    expect(folderChoice("/Users/me/new", repos)).toEqual({ register: "/Users/me/new" });
  });
});
