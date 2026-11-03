// What a project tab remembers, ported from NestKit's ProjectState (AppStore.swift): its
// workspace, its tool panes and how its side panels are arranged.
import { normalizedFolder, runPane, terminalPane, type ToolPane } from "./tools.ts";
import { WorkspaceLayout, type DropSide, type OpenOutcome, type Size } from "./workspace.ts";

export type ProjectView = "workspace" | "board" | "artifacts";

/** The status bar's switch, in order; the Pixies tab has no board. */
export function viewChoices(pixies: boolean): ProjectView[] {
  return pixies ? ["workspace", "artifacts"] : ["workspace", "board", "artifacts"];
}

export type RightCard = "needsYou" | "goals";

export class ProjectState {
  layout = new WorkspaceLayout();
  leftCollapsed = false;
  rightCollapsed = false;
  // The right panel's open cards; they share its height.
  openCards = new Set<RightCard>(["needsYou", "goals"]);
  view: ProjectView = "workspace";
  // The chat highlighted in the sidebar.
  selectedChat: string | null = null;
  // The terminal, browser and run panes in the workspace, by pane id.
  tools = new Map<string, ToolPane>();

  copy(): ProjectState {
    const next = new ProjectState();
    next.layout = this.layout.copy();
    next.leftCollapsed = this.leftCollapsed;
    next.rightCollapsed = this.rightCollapsed;
    next.openCards = new Set(this.openCards);
    next.view = this.view;
    next.selectedChat = this.selectedChat;
    next.tools = new Map(this.tools);
    return next;
  }

  /** Opens a chat by click; the workspace view comes back if the board was showing. */
  openChat(id: string, size: Size): OpenOutcome {
    this.view = "workspace";
    this.selectedChat = id;
    const outcome = this.layout.open(id, size);
    this.pruneTools();
    return outcome;
  }

  dropChat(id: string, target: string | null, side: DropSide): void {
    this.view = "workspace";
    if (this.layout.drop(id, target, side) !== null) this.selectedChat = id;
    this.pruneTools();
  }

  /** Shows `next` in `old`'s pane, as when a draft becomes a chat; it stays selected. */
  replaceChat(old: string, next: string): void {
    this.layout.replace(old, next);
    this.selectedChat = next;
    this.pruneTools();
  }

  closePane(id: string): void {
    this.layout.remove(id);
    if (this.selectedChat === id) this.selectedChat = this.layout.focused;
    this.pruneTools();
  }

  /** Opens a terminal, browser or run pane by the same rules as a chat. */
  openTool(pane: ToolPane, size: Size): void {
    this.view = "workspace";
    this.tools.set(pane.id, pane);
    this.layout.open(pane.id, size);
    this.pruneTools();
  }

  /** The terminal for `folder`, focused: an open one, or a new one (`opened`). */
  terminal(folder: string, size: Size): { pane: ToolPane; opened: boolean } {
    const normal = normalizedFolder(folder);
    const open = this.openTools.find((p) => p.kind === "terminal" && p.folder === normal);
    if (open !== undefined) {
      this.view = "workspace";
      this.layout.open(open.id, size);
      return { pane: open, opened: false };
    }
    const pane = terminalPane(normal);
    this.openTool(pane, size);
    return { pane, opened: true };
  }

  /** The status bar's Terminal: the project's open terminal, else a new one in `folder`. */
  projectTerminal(folder: string, size: Size): { pane: ToolPane; opened: boolean } {
    const open = this.openTools.find((p) => p.kind === "terminal");
    if (open !== undefined) {
      this.view = "workspace";
      this.layout.open(open.id, size);
      return { pane: open, opened: false };
    }
    const pane = terminalPane(folder);
    this.openTool(pane, size);
    return { pane, opened: true };
  }

  /** The run output pane of `folder` (B108): an open one, or a new one beside `chat`. */
  runOutput(folder: string, session: string, chat: string, size: Size): ToolPane {
    this.view = "workspace";
    const open = this.openTools.find((p) => p.kind === "run" && p.folder === folder);
    if (open !== undefined) return open;
    const pane = runPane(folder, session);
    this.tools.set(pane.id, pane);
    this.layout.place(pane.id, chat, size);
    this.pruneTools();
    return pane;
  }

  setURL(url: string, pane: string): void {
    const tool = this.tools.get(pane);
    if (tool !== undefined) this.tools.set(pane, { ...tool, url });
  }

  /** Tool panes in reading order, as they are saved. */
  get openTools(): ToolPane[] {
    return this.layout.leaves.flatMap((id) => {
      const tool = this.tools.get(id);
      return tool === undefined ? [] : [tool];
    });
  }

  focusPane(id: string): void {
    this.layout.focus(id);
    this.selectedChat = this.layout.focused;
  }

  toggleCard(card: RightCard): void {
    if (!this.openCards.delete(card)) this.openCards.add(card);
  }

  /** A deleted chat leaves the workspace. */
  forget(id: string): void {
    this.closePane(id);
  }

  // A pane that left the workspace (closed, or replaced) is forgotten.
  private pruneTools(): void {
    for (const id of [...this.tools.keys()]) {
      if (!this.layout.contains(id)) this.tools.delete(id);
    }
  }
}
