// The live side of terminal and browser panes, by pane id, as the Mac's ToolSessions: a
// shell with its screen, a browser window's label. They outlive the pane's view, so
// switching tabs, views or projects, moving or maximising a pane keeps them; closing the
// pane or removing its project ends them.

export interface Ending {
  end(): void;
}

export class ToolSessions<T extends Ending> {
  private readonly sessions = new Map<string, T>();

  /** The pane's session, made the first time it is asked for. */
  session(pane: string, make: () => T): T {
    const found = this.sessions.get(pane);
    if (found !== undefined) return found;
    const made = make();
    this.sessions.set(pane, made);
    return made;
  }

  find(pane: string): T | undefined {
    return this.sessions.get(pane);
  }

  all(): T[] {
    return [...this.sessions.values()];
  }

  /** Ends every session whose pane is not in `panes`. */
  keep(panes: ReadonlySet<string>): void {
    for (const [id, session] of this.sessions) {
      if (panes.has(id)) continue;
      this.sessions.delete(id);
      session.end();
    }
  }
}

/**
 * A browser pane's window: the label back, forward and reload act on, and that Return
 * opens the next page in, so each pane keeps one window. The pane's view follows it.
 */
export class BrowserSession implements Ending {
  private current: string | null = null;
  private readonly listeners = new Set<() => void>();

  get label(): string | null {
    return this.current;
  }

  set label(next: string | null) {
    if (next === this.current) return;
    this.current = next;
    for (const listener of this.listeners) listener();
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  remember(label: string | null): void {
    this.label = label;
  }

  end(): void {
    this.label = null;
  }
}

export const browsers = new ToolSessions<BrowserSession>();

/** A browser window closed (nest://browser-closed): the pane it belonged to has none now. */
export function browserClosed(sessions: ToolSessions<BrowserSession>, label: string): void {
  for (const session of sessions.all()) {
    if (session.label === label) session.label = null;
  }
}
