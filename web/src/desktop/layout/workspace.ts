// The split workspace of a project, ported from NestKit's WorkspaceLayout (B25, B93, B108):
// leaves are pane ids (chats, or tool panes whose id starts with their kind), splits
// divide their space by `ratio`, the first child's share.

export type SplitDirection = "row" | "column";
export type DropSide = "left" | "right" | "top" | "bottom";

export type LayoutNode =
  | { leaf: string }
  | {
      split: number;
      direction: SplitDirection;
      ratio: number;
      first: LayoutNode;
      second: LayoutNode;
    };

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface GutterFrame {
  split: number;
  direction: SplitDirection;
  ratio: number;
  // The divider line itself.
  frame: Rect;
  // The split's length along its direction without the gutter: a drag of this many pixels
  // moves the ratio by 1.
  span: number;
}

export type OpenOutcome = "focused" | "added" | { replaced: string };

export type RowState = "focused" | "open" | "closed";

export type PaneKind = "chat" | "terminal" | "browser" | "run";

/** A pane's kind from its id: tool panes carry their kind as a prefix. */
export function paneKind(id: string): PaneKind {
  for (const kind of ["terminal", "browser", "run"] as const) {
    if (id.startsWith(`${kind}:`)) return kind;
  }
  return "chat";
}

export const MAXIMUM_PANES = 4;
export const MINIMUM_PANE_WIDTH = 280;
export const MINIMUM_PANE_HEIGHT = 180;
// Panes sit edge to edge with a 1 pixel divider (B93).
export const GUTTER = 1;
export const GUTTER_GRAB_WIDTH = 10;
// A new pane goes beside another when both halves keep at least this width.
export const MINIMUM_SIDE_BY_SIDE_WIDTH = 360;

export function leavesOf(node: LayoutNode | null): string[] {
  if (node === null) return [];
  return "leaf" in node ? [node.leaf] : [...leavesOf(node.first), ...leavesOf(node.second)];
}

function removing(node: LayoutNode, id: string): LayoutNode | null {
  if ("leaf" in node) return node.leaf === id ? null : node;
  const first = removing(node.first, id);
  if (first === null) return removing(node.second, id);
  const second = removing(node.second, id);
  if (second === null) return first;
  return { ...node, first, second };
}

function mapLeaves(node: LayoutNode, transform: (id: string) => string): LayoutNode {
  if ("leaf" in node) return { leaf: transform(node.leaf) };
  return {
    ...node,
    first: mapLeaves(node.first, transform),
    second: mapLeaves(node.second, transform),
  };
}

function replacingLeaf(node: LayoutNode, target: string, next: LayoutNode): LayoutNode {
  if ("leaf" in node) return node.leaf === target ? next : node;
  return {
    ...node,
    first: replacingLeaf(node.first, target, next),
    second: replacingLeaf(node.second, target, next),
  };
}

function settingRatio(node: LayoutNode, ratio: number, split: number): LayoutNode {
  if ("leaf" in node) return node;
  return {
    ...node,
    ratio: node.split === split ? ratio : node.ratio,
    first: settingRatio(node.first, ratio, split),
    second: settingRatio(node.second, ratio, split),
  };
}

function minimumExtent(node: LayoutNode, horizontal: boolean): number {
  if ("leaf" in node) return horizontal ? MINIMUM_PANE_WIDTH : MINIMUM_PANE_HEIGHT;
  const a = minimumExtent(node.first, horizontal);
  const b = minimumExtent(node.second, horizontal);
  return (node.direction === "row") === horizontal ? a + b + GUTTER : Math.max(a, b);
}

function divide(rect: Rect, direction: SplitDirection, ratio: number) {
  if (direction === "row") {
    const width = (rect.width - GUTTER) * ratio;
    return {
      first: { x: rect.x, y: rect.y, width, height: rect.height },
      gutter: { x: rect.x + width, y: rect.y, width: GUTTER, height: rect.height },
      second: {
        x: rect.x + width + GUTTER,
        y: rect.y,
        width: rect.width - width - GUTTER,
        height: rect.height,
      },
    };
  }
  const height = (rect.height - GUTTER) * ratio;
  return {
    first: { x: rect.x, y: rect.y, width: rect.width, height },
    gutter: { x: rect.x, y: rect.y + height, width: rect.width, height: GUTTER },
    second: {
      x: rect.x,
      y: rect.y + height + GUTTER,
      width: rect.width,
      height: rect.height - height - GUTTER,
    },
  };
}

function frames(
  node: LayoutNode,
  rect: Rect,
  leaves: { pane: string; frame: Rect }[],
  splits: Map<number, Rect>,
) {
  if ("leaf" in node) {
    leaves.push({ pane: node.leaf, frame: rect });
    return;
  }
  splits.set(node.split, rect);
  const parts = divide(rect, node.direction, node.ratio);
  frames(node.first, parts.first, leaves, splits);
  frames(node.second, parts.second, leaves, splits);
}

function gutters(node: LayoutNode, rect: Rect): GutterFrame[] {
  if ("leaf" in node) return [];
  const parts = divide(rect, node.direction, node.ratio);
  const span =
    node.direction === "row" ? rect.width - parts.gutter.width : rect.height - parts.gutter.height;
  return [
    { split: node.split, direction: node.direction, ratio: node.ratio, frame: parts.gutter, span },
    ...gutters(node.first, parts.first),
    ...gutters(node.second, parts.second),
  ];
}

function findSplit(node: LayoutNode, id: number): Extract<LayoutNode, { split: number }> | null {
  if ("leaf" in node) return null;
  if (node.split === id) return node;
  return findSplit(node.first, id) ?? findSplit(node.second, id);
}

function contains(rect: Rect, x: number, y: number): boolean {
  return x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height;
}

/** Where a divider is grabbed: wider than the line, centred on it. */
export function grabArea(gutter: GutterFrame): Rect {
  const reach = (GUTTER_GRAB_WIDTH - GUTTER) / 2;
  const { frame } = gutter;
  return gutter.direction === "row"
    ? { ...frame, x: frame.x - reach, width: frame.width + 2 * reach }
    : { ...frame, y: frame.y - reach, height: frame.height + 2 * reach };
}

export interface WorkspaceData {
  root: LayoutNode | null;
  maximized: string | null;
  focused: string | null;
  nextSplit: number;
}

/**
 * One project's split workspace of up to four panes. Mutating, like the Swift struct it
 * ports; `copy` before changing one held in React state. Nodes are never changed in
 * place, so a copy shares them.
 */
export class WorkspaceLayout {
  root: LayoutNode | null = null;
  maximized: string | null = null;
  focused: string | null = null;
  private nextSplit = 1;

  static from(data: WorkspaceData): WorkspaceLayout {
    const layout = new WorkspaceLayout();
    layout.root = data.root;
    layout.maximized = data.maximized;
    layout.focused = data.focused;
    layout.nextSplit = data.nextSplit;
    return layout;
  }

  toJSON(): WorkspaceData {
    return {
      root: this.root,
      maximized: this.maximized,
      focused: this.focused,
      nextSplit: this.nextSplit,
    };
  }

  copy(): WorkspaceLayout {
    return WorkspaceLayout.from(this.toJSON());
  }

  get leaves(): string[] {
    return leavesOf(this.root);
  }

  contains(pane: string): boolean {
    return this.leaves.includes(pane);
  }

  /** Pane frames in reading order for a workspace of `size`. */
  paneFrames(size: Size): { pane: string; frame: Rect }[] {
    const leaves: { pane: string; frame: Rect }[] = [];
    if (this.root !== null) {
      frames(this.root, { x: 0, y: 0, ...size }, leaves, new Map());
    }
    return leaves;
  }

  /** The dividers of every split, outer splits first. */
  gutterFrames(size: Size): GutterFrame[] {
    return this.root === null ? [] : gutters(this.root, { x: 0, y: 0, ...size });
  }

  /** The pane under a point: the maximized one anywhere, else the pane whose frame holds it. */
  paneAt(x: number, y: number, size: Size): string | null {
    if (!contains({ x: 0, y: 0, ...size }, x, y)) return null;
    if (this.maximized !== null) return this.maximized;
    return this.paneFrames(size).find((p) => contains(p.frame, x, y))?.pane ?? null;
  }

  /**
   * Opens a pane by click: focus it if open; otherwise add it next to the largest pane (to
   * its right when both halves stay wide enough to read, else below it); with four open,
   * the last pane in reading order shows it instead.
   */
  open(pane: string, size: Size): OpenOutcome {
    if (this.contains(pane)) {
      this.focused = pane;
      if (this.maximized !== null) this.maximized = pane;
      return "focused";
    }
    const outcome = this.add(pane, size);
    this.maximized = null;
    this.focused = pane;
    return outcome;
  }

  private add(pane: string, size: Size): OpenOutcome {
    const last = this.leaves.at(-1);
    if (this.leaves.length >= MAXIMUM_PANES && last !== undefined && this.root !== null) {
      this.root = replacingLeaf(this.root, last, { leaf: pane });
      return { replaced: last };
    }
    if (this.root === null) {
      this.root = { leaf: pane };
      return "added";
    }
    const all = this.paneFrames(size);
    const area = (r: Rect) => r.width * r.height;
    const target =
      all.find((p) => p.pane === this.maximized) ??
      all.reduce((best, p) => (area(p.frame) > area(best.frame) ? p : best));
    const wide =
      this.maximized !== null || (target.frame.width - GUTTER) / 2 >= MINIMUM_SIDE_BY_SIDE_WIDTH;
    this.insert(pane, target.pane, wide ? "right" : "bottom");
    return "added";
  }

  /**
   * Adds a pane next to `target` without taking the focus (B108); with four open, the last
   * pane other than `target` shows it. Without `target` open it opens as a click would.
   */
  place(pane: string, target: string, size: Size): void {
    if (this.contains(pane)) return;
    if (!this.contains(target)) {
      this.open(pane, size);
      return;
    }
    const last = this.leaves.filter((id) => id !== target).at(-1);
    if (this.leaves.length >= MAXIMUM_PANES && last !== undefined) {
      this.replace(last, pane);
      if (this.focused === pane) this.focused = target;
      return;
    }
    const frame = this.paneFrames(size).find((p) => p.pane === target)?.frame;
    const wide =
      this.maximized !== null ||
      (frame !== undefined && (frame.width - GUTTER) / 2 >= MINIMUM_SIDE_BY_SIDE_WIDTH);
    this.insert(pane, target, wide ? "right" : "bottom");
  }

  /**
   * Drops a pane onto another: splits the target on `side`. One not open yet replaces the
   * target when four are open. Into an empty workspace it simply opens.
   */
  drop(pane: string, target: string | null, side: DropSide): OpenOutcome | null {
    if (this.root === null) {
      this.root = { leaf: pane };
      this.focused = pane;
      return "added";
    }
    if (target === null || pane === target || !this.contains(target)) return null;
    let outcome: OpenOutcome;
    if (!this.contains(pane) && this.leaves.length >= MAXIMUM_PANES) {
      this.replace(target, pane);
      outcome = { replaced: target };
    } else {
      this.root = removing(this.root, pane);
      this.insert(pane, target, side);
      outcome = "added";
    }
    this.focus(pane);
    return outcome;
  }

  swap(a: string, b: string): void {
    if (this.root === null || !this.contains(a) || !this.contains(b)) return;
    this.root = mapLeaves(this.root, (id) => (id === a ? b : id === b ? a : id));
  }

  /** Shows `pane` in `target`'s place; an open pane swaps places instead. */
  replace(target: string, pane: string): void {
    if (this.root === null || !this.contains(target)) return;
    if (this.contains(pane)) {
      this.swap(target, pane);
      return;
    }
    this.root = replacingLeaf(this.root, target, { leaf: pane });
    if (this.focused === target) this.focused = pane;
    if (this.maximized === target) this.maximized = null;
  }

  /** Closes a pane; its sibling takes the space. */
  remove(pane: string): void {
    if (this.root === null || !this.contains(pane)) return;
    this.root = removing(this.root, pane);
    if (this.maximized === pane) this.maximized = null;
    if (this.focused === pane) this.focused = this.leaves[0] ?? null;
  }

  /** Focus dim (B93): with two or more panes on screen, every pane but the focused one. */
  isDimmed(pane: string): boolean {
    return (
      this.maximized === null &&
      this.leaves.length > 1 &&
      this.contains(pane) &&
      this.focused !== pane
    );
  }

  /**
   * How a chat's sidebar row shows its pane: focused when its pane has the focus or it is
   * the only chat open (beside tool panes), open when another pane has it, else closed.
   */
  rowState(chat: string): RowState {
    if (paneKind(chat) !== "chat" || !this.contains(chat)) return "closed";
    const chats = this.leaves.filter((id) => paneKind(id) === "chat");
    return this.focused === chat || (chats.length === 1 && chats[0] === chat) ? "focused" : "open";
  }

  focus(pane: string): void {
    if (this.contains(pane)) this.focused = pane;
  }

  /** Maximizes the pane, or restores the split when it is the maximized one. */
  toggleMaximize(pane: string): void {
    if (!this.contains(pane)) return;
    this.maximized = this.maximized === pane ? null : pane;
    this.focused = pane;
  }

  restore(): void {
    this.maximized = null;
  }

  /** Sets a split's ratio, kept within what its panes' minimum sizes allow in `size`. */
  resize(split: number, ratio: number, size: Size): void {
    if (this.root === null) return;
    const splits = new Map<number, Rect>();
    frames(this.root, { x: 0, y: 0, ...size }, [], splits);
    const rect = splits.get(split);
    const node = findSplit(this.root, split);
    if (rect === undefined || node === null) return;
    const horizontal = node.direction === "row";
    const total = (horizontal ? rect.width : rect.height) - GUTTER;
    const lower = minimumExtent(node.first, horizontal) / total;
    const upper = 1 - minimumExtent(node.second, horizontal) / total;
    // Too small for both minimums: share the space in proportion to them.
    const clamped =
      lower > upper ? lower / (lower + 1 - upper) : Math.min(Math.max(ratio, lower), upper);
    this.root = settingRatio(this.root, clamped, split);
  }

  private insert(pane: string, target: string, side: DropSide): void {
    if (this.root === null) return;
    const split = this.nextSplit;
    this.nextSplit += 1;
    const direction: SplitDirection = side === "left" || side === "right" ? "row" : "column";
    const before = side === "left" || side === "top";
    this.root = replacingLeaf(this.root, target, {
      split,
      direction,
      ratio: 0.5,
      first: { leaf: before ? pane : target },
      second: { leaf: before ? target : pane },
    });
  }
}

export type DropZone =
  { open: true } | { split: DropSide } | { replace: true } | { swap: true } | { none: true };

/** What a drag brings: a chat from the sidebar, or an open pane by its header. */
export type DragKind = "chat" | "pane";

/**
 * The zone a drop at (x, y) within a pane of `size` takes, as the Mac's DropZone: the top
 * and bottom quarters split vertically, the middle splits left or right. `target` is null
 * for the empty workspace.
 */
export function dropZone(
  x: number,
  y: number,
  size: Size,
  kind: DragKind,
  target: { isDragged: boolean; draggedIsOpen: boolean; openCount: number } | null,
): DropZone {
  if (target === null) return { open: true };
  if (target.isDragged) return { none: true };
  if (kind === "pane") return { swap: true };
  if (!target.draggedIsOpen && target.openCount >= MAXIMUM_PANES) return { replace: true };
  const top = y / size.height;
  if (top < 0.26) return { split: "top" };
  if (top > 0.74) return { split: "bottom" };
  return { split: x / size.width < 0.5 ? "left" : "right" };
}

/** The pane under a point of the workspace and the zone a drop of `dragged` takes there. */
export function dropHit(
  layout: WorkspaceLayout,
  x: number,
  y: number,
  size: Size,
  dragged: string,
  kind: DragKind,
): { pane: string; frame: Rect; zone: DropZone } | null {
  const placements = layout.paneFrames(size);
  const hit = placements.find((p) => contains(p.frame, x, y));
  if (hit === undefined) return null;
  const target = {
    isDragged: hit.pane === dragged,
    draggedIsOpen: placements.some((p) => p.pane === dragged),
    openCount: placements.length,
  };
  return {
    pane: hit.pane,
    frame: hit.frame,
    zone: dropZone(x - hit.frame.x, y - hit.frame.y, hit.frame, kind, target),
  };
}
