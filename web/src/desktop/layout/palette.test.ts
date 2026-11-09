// Ported from NestKitTests/CommandPaletteTests.swift: what the palette lists, how a query
// filters it, and how the selection moves.
import { describe, expect, it } from "vitest";
import {
  catalog,
  move,
  palette,
  search,
  selected,
  showMessages,
  visible,
  type CatalogInput,
  type PaletteItem,
} from "./palette.ts";

function input(overrides: Partial<CatalogInput> = {}): CatalogInput {
  return {
    open: ["todo-ui", "map-viewer"],
    current: "todo-ui",
    chats: [
      { id: "c1", title: "Validate the form", project: "todo-ui", status: "Running" },
      { id: "c2", title: "Dark mode", project: "todo-ui", status: "Idle" },
      { id: "h1", title: "Retry", project: "map-viewer", status: "Question" },
      { id: "x1", title: "Closed tab", project: "recipes", status: "Idle" },
    ],
    view: "workspace",
    leftCollapsed: false,
    rightCollapsed: false,
    editor: "Zed",
    attention: (project) => (project === "map-viewer" ? 1 : 0),
    ...overrides,
  };
}

const hit = (pane: string, event: number | null): PaletteItem => ({
  group: "Messages",
  title: `Hit ${pane}`,
  subtitle: "todo-ui · Claude",
  action: { openMessage: pane, project: "todo-ui", event },
});

describe("command palette", () => {
  it("lists open projects' chats, the project's commands, then the other projects", () => {
    const items = catalog(input());
    expect(items.map((i) => i.title)).toEqual([
      "Validate the form",
      "Dark mode",
      "Retry",
      "New chat in todo-ui",
      "New terminal in todo-ui",
      "New browser",
      "Show the Board view",
      "Show the Artifacts view",
      "Collapse the chat sidebar",
      "Collapse the activity panel",
      "Show usage",
      "Open todo-ui in Zed",
      "Go to map-viewer",
    ]);
    expect(items[2]?.subtitle).toBe("map-viewer · Question");
    expect(items.at(-1)?.subtitle).toBe("1 need you");
  });

  it("offers what the project's state does not show yet", () => {
    const titles = catalog(input({ view: "board", leftCollapsed: true, rightCollapsed: true })).map(
      (i) => i.title,
    );
    expect(titles).toContain("Show the Workspace view");
    expect(titles).toContain("Expand the chat sidebar");
    expect(titles).toContain("Expand the activity panel");
    expect(catalog(input({ current: null })).some((i) => i.group === "Commands")).toBe(false);
    // B152: with no editor installed there is nothing to open the project in.
    expect(catalog(input({ editor: null })).some((i) => "openInEditor" in i.action)).toBe(false);
    // General's folder belongs to Nest: no terminal there (B110).
    const general = catalog(input({ current: "general" }));
    expect(general.some((i) => "newTerminal" in i.action)).toBe(false);
    expect(general.some((i) => "newChat" in i.action)).toBe(true);
  });

  it("filters by every word and selects the first match again", () => {
    let p = move(palette(catalog(input())), 2);
    p = search(p, "  cv  MODE ");
    expect(p.selection).toBe(0);
    expect(visible(p).map((i) => i.title)).toEqual(["Dark mode"]);
    p = search(p, "question");
    expect(selected(p)?.title).toBe("Retry");
    p = search(p, "nothing like this");
    expect(selected(p)).toBeNull();
    expect(move(p, 1).selection).toBe(0);
  });

  it("wraps the selection at both ends", () => {
    let p = palette(catalog(input()));
    p = move(p, -1);
    expect(selected(p)?.title).toBe("Go to map-viewer");
    p = move(p, 1);
    expect(selected(p)?.title).toBe("Validate the form");
  });

  it("adds message hits once each, after the matches, for the current query only", () => {
    let p = search(palette(catalog(input())), "form");
    p = showMessages(p, "for", [hit("s1", null)]);
    expect(p.messages).toHaveLength(0);
    p = showMessages(p, "form", [hit("s1", null), hit("s1", 14), hit("s1", 14)]);
    expect(visible(p).map((i) => i.title)).toEqual(["Validate the form", "Hit s1", "Hit s1"]);
    // A query too short to search drops them.
    expect(search(p, "f").messages).toHaveLength(0);
  });

  it("keeps the selection in range when fewer hits come back", () => {
    let p = search(palette(catalog(input())), "zz");
    p = showMessages(p, "zz", [hit("a", 1), hit("b", 2), hit("c", 3), hit("d", 4)]);
    p = move(p, 3);
    expect(p.selection).toBe(3);
    p = showMessages(p, "zz", [hit("a", 1)]);
    expect(p.selection).toBe(0);
  });
});
