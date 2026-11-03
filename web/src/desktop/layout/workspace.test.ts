// Ported from NestKitTests/WorkspaceLayoutTests.swift and the drop zone rules: the rules a
// user relies on when opening, dragging, closing and focusing panes.
import { describe, expect, it } from "vitest";
import {
  dropHit,
  dropZone,
  WorkspaceLayout,
  type DropSide,
  type LayoutNode,
  type Size,
} from "./workspace.ts";

const wide: Size = { width: 1000, height: 600 };

const leaf = (id: string): LayoutNode => ({ leaf: id });
const row = (split: number, first: LayoutNode, second: LayoutNode, ratio = 0.5): LayoutNode => ({
  split,
  direction: "row",
  ratio,
  first,
  second,
});
const column = (split: number, first: LayoutNode, second: LayoutNode): LayoutNode => ({
  split,
  direction: "column",
  ratio: 0.5,
  first,
  second,
});

/** a | b, with a split into a over c, and b into b over d. */
function fourPanes(): WorkspaceLayout {
  const layout = new WorkspaceLayout();
  for (const id of ["a", "b", "c", "d"]) layout.open(id, wide);
  return layout;
}

function ratioOf(node: LayoutNode | null, split: number): number | null {
  if (node === null || "leaf" in node) return null;
  if (node.split === split) return node.ratio;
  return ratioOf(node.first, split) ?? ratioOf(node.second, split);
}

describe("opening panes", () => {
  it("splits the largest pane, beside it while two columns fit, else below", () => {
    const layout = new WorkspaceLayout();
    expect(layout.open("a", wide)).toBe("added");
    expect(layout.root).toEqual(leaf("a"));
    layout.open("b", wide);
    expect(layout.root).toEqual(row(1, leaf("a"), leaf("b")));
    layout.open("c", wide);
    expect(layout.root).toEqual(row(1, column(2, leaf("a"), leaf("c")), leaf("b")));
    layout.open("d", wide);
    expect(layout.leaves).toEqual(["a", "c", "b", "d"]);
    expect(layout.focused).toBe("d");
  });

  it("stacks the second pane in a tall or narrow workspace", () => {
    const tall = new WorkspaceLayout();
    tall.open("a", { width: 600, height: 900 });
    tall.open("b", { width: 600, height: 900 });
    expect(tall.root).toEqual(column(1, leaf("a"), leaf("b")));
    // A nearly square middle with both side panels open still fits two columns.
    const square = new WorkspaceLayout();
    square.open("a", { width: 860, height: 820 });
    square.open("b", { width: 860, height: 820 });
    expect(square.root).toEqual(row(1, leaf("a"), leaf("b")));
  });

  it("shows a fifth pane in the last pane's place, even when maximized", () => {
    const layout = fourPanes();
    expect(layout.open("e", wide)).toEqual({ replaced: "d" });
    expect(layout.leaves).toEqual(["a", "c", "b", "e"]);
    expect(layout.focused).toBe("e");
    layout.toggleMaximize("a");
    expect(layout.open("f", wide)).toEqual({ replaced: "e" });
    expect(layout.maximized).toBeNull();
  });

  it("focuses an open pane without moving anything, keeping a maximized view", () => {
    const layout = fourPanes();
    const before = layout.root;
    expect(layout.open("a", wide)).toBe("focused");
    expect(layout.root).toBe(before);
    expect(layout.focused).toBe("a");
    layout.toggleMaximize("a");
    layout.open("c", wide);
    expect(layout.maximized).toBe("c");
  });

  it("splits the maximized pane for a new one and shows the split again", () => {
    const size = { width: 600, height: 900 };
    const layout = new WorkspaceLayout();
    layout.open("a", size);
    layout.open("b", size);
    layout.toggleMaximize("b");
    layout.open("c", size);
    expect(layout.root).toEqual(column(1, leaf("a"), row(2, leaf("b"), leaf("c"))));
    expect(layout.maximized).toBeNull();
  });

  it("places a run pane beside its chat without taking the focus", () => {
    const layout = new WorkspaceLayout();
    layout.open("a", wide);
    layout.place("run:1", "a", wide);
    expect(layout.leaves).toEqual(["a", "run:1"]);
    expect(layout.focused).toBe("a");
    const full = fourPanes();
    full.focus("d");
    full.place("run:2", "d", wide);
    expect(full.leaves).toEqual(["a", "c", "run:2", "d"]);
    expect(full.focused).toBe("d");
  });
});

describe("dropping panes", () => {
  it.each<[DropSide, LayoutNode]>([
    ["left", row(1, leaf("b"), leaf("a"))],
    ["right", row(1, leaf("a"), leaf("b"))],
    ["top", column(1, leaf("b"), leaf("a"))],
    ["bottom", column(1, leaf("a"), leaf("b"))],
  ])("splits the target on the %s", (side, expected) => {
    const layout = new WorkspaceLayout();
    layout.open("a", wide);
    expect(layout.drop("b", "a", side)).toBe("added");
    expect(layout.root).toEqual(expected);
    expect(layout.focused).toBe("b");
  });

  it("moves an open pane, and replaces the target with a new one when full", () => {
    const layout = new WorkspaceLayout();
    for (const id of ["a", "b", "c"]) layout.open(id, wide);
    layout.drop("b", "c", "right");
    expect(layout.leaves).toEqual(["a", "c", "b"]);

    const full = fourPanes();
    expect(full.drop("e", "c", "left")).toEqual({ replaced: "c" });
    expect(full.leaves).toEqual(["a", "e", "b", "d"]);
    // An open pane still splits when full.
    expect(full.drop("d", "a", "top")).toBe("added");
    expect(full.leaves).toEqual(["d", "a", "e", "b"]);
  });

  it("opens into an empty workspace and ignores meaningless drops", () => {
    const empty = new WorkspaceLayout();
    expect(empty.drop("a", null, "left")).toBe("added");
    expect(empty.root).toEqual(leaf("a"));
    const layout = fourPanes();
    const before = layout.toJSON();
    expect(layout.drop("a", "a", "left")).toBeNull();
    expect(layout.drop("e", "zzz", "left")).toBeNull();
    expect(layout.drop("e", null, "left")).toBeNull();
    expect(layout.toJSON()).toEqual(before);
  });

  it("picks the zone by where the pointer is over a pane", () => {
    const size = { width: 400, height: 400 };
    const target = { isDragged: false, draggedIsOpen: false, openCount: 2 };
    expect(dropZone(200, 50, size, "chat", target)).toEqual({ split: "top" });
    expect(dropZone(200, 350, size, "chat", target)).toEqual({ split: "bottom" });
    expect(dropZone(100, 200, size, "chat", target)).toEqual({ split: "left" });
    expect(dropZone(300, 200, size, "chat", target)).toEqual({ split: "right" });
    expect(dropZone(300, 200, size, "pane", target)).toEqual({ swap: true });
    expect(dropZone(300, 200, size, "chat", { ...target, openCount: 4 })).toEqual({
      replace: true,
    });
    expect(dropZone(300, 200, size, "chat", { ...target, isDragged: true })).toEqual({
      none: true,
    });
    expect(dropZone(0, 0, size, "chat", null)).toEqual({ open: true });
  });

  it("finds the pane under the pointer, none over a gutter", () => {
    const layout = new WorkspaceLayout();
    layout.open("a", wide);
    layout.open("b", wide);
    expect(dropHit(layout, 900, 300, wide, "c", "chat")?.pane).toBe("b");
    expect(dropHit(layout, 499.7, 300, wide, "c", "chat")).toBeNull();
    expect(dropHit(layout, 100, 300, wide, "a", "chat")?.zone).toEqual({ none: true });
  });
});

describe("closing, swapping and resizing", () => {
  it("collapses a closed pane's split and moves the focus on", () => {
    const layout = fourPanes();
    layout.remove("c");
    expect(layout.root).toEqual(row(1, leaf("a"), column(3, leaf("b"), leaf("d"))));
    layout.toggleMaximize("d");
    layout.remove("d");
    expect(layout.maximized).toBeNull();
    expect(layout.focused).toBe("a");
    layout.remove("a");
    layout.remove("b");
    expect(layout.root).toBeNull();
    expect(layout.focused).toBeNull();
  });

  it("swaps panes, and replace swaps when the chat is open already", () => {
    const layout = fourPanes();
    layout.swap("a", "d");
    expect(layout.leaves).toEqual(["d", "c", "b", "a"]);
    layout.replace("d", "b");
    expect(layout.leaves).toEqual(["b", "c", "d", "a"]);
    layout.focus("c");
    layout.toggleMaximize("c");
    layout.replace("c", "e");
    expect(layout.focused).toBe("e");
    expect(layout.maximized).toBeNull();
  });

  it("keeps panes above their minimum size when resizing", () => {
    const layout = fourPanes();
    layout.resize(1, 0.6, wide);
    expect(ratioOf(layout.root, 1)).toBe(0.6);
    layout.resize(1, 0.05, wide);
    expect(ratioOf(layout.root, 1)).toBe(280 / 999);
    layout.resize(1, 0.99, wide);
    expect(ratioOf(layout.root, 1)).toBe(1 - 280 / 999);
    layout.resize(3, 0.9, wide);
    expect(ratioOf(layout.root, 3)).toBe(1 - 180 / 599);
    // Too small for both: the space is shared by their minimums.
    const small = new WorkspaceLayout();
    small.open("a", wide);
    small.open("b", wide);
    small.resize(1, 0.9, { width: 500, height: 600 });
    expect(ratioOf(small.root, 1)).toBeCloseTo(0.5);
  });

  it("lays panes out edge to edge with a one pixel divider", () => {
    const frames = fourPanes().paneFrames(wide);
    expect(frames.map((f) => f.pane)).toEqual(["a", "c", "b", "d"]);
    expect(frames[0]?.frame).toEqual({ x: 0, y: 0, width: 499.5, height: 299.5 });
    expect(frames[3]?.frame).toEqual({ x: 500.5, y: 300.5, width: 499.5, height: 299.5 });
  });

  it("gives every point of the workspace to a maximized pane", () => {
    const layout = new WorkspaceLayout();
    layout.open("a", wide);
    layout.open("b", wide);
    expect(layout.paneAt(10, 10, wide)).toBe("a");
    expect(layout.paneAt(500, 300, wide)).toBeNull();
    layout.toggleMaximize("b");
    expect(layout.paneAt(10, 10, wide)).toBe("b");
    expect(layout.paneAt(1001, 300, wide)).toBeNull();
  });
});

describe("focus dim and sidebar rows (B93)", () => {
  it("dims every pane but the focused one while two or more show", () => {
    const one = new WorkspaceLayout();
    one.open("a", wide);
    expect(one.isDimmed("a")).toBe(false);
    const layout = fourPanes();
    layout.focus("b");
    expect(["a", "b", "c", "d"].map((id) => layout.isDimmed(id))).toEqual([
      true,
      false,
      true,
      true,
    ]);
    expect(layout.isDimmed("zzz")).toBe(false);
  });

  it("dims nothing while a pane is maximized", () => {
    const layout = fourPanes();
    layout.toggleMaximize("a");
    expect(layout.isDimmed("b")).toBe(false);
    layout.toggleMaximize("a");
    expect(layout.isDimmed("b")).toBe(true);
  });

  it("marks a chat's row focused, open or closed", () => {
    const layout = new WorkspaceLayout();
    expect(layout.rowState("a")).toBe("closed");
    layout.open("a", wide);
    layout.open("terminal:1", wide);
    // The only chat beside a focused terminal still reads as focused.
    expect(layout.rowState("a")).toBe("focused");
    expect(layout.rowState("terminal:1")).toBe("closed");
    layout.open("b", wide);
    layout.focus("terminal:1");
    expect(layout.rowState("a")).toBe("open");
    expect(layout.rowState("b")).toBe("open");
    layout.focus("b");
    expect(layout.rowState("b")).toBe("focused");
  });
});
