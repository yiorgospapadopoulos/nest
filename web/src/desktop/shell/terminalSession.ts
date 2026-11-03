// A terminal pane's wiring between xterm.js and the Tauri side's pty (bridge.ts), apart from
// the view so it can be tested without a browser terminal.
import type { Bridge, Pty } from "../bridge.ts";

interface Disposable {
  dispose(): void;
}

/** The part of xterm.js's Terminal this needs. */
export interface TerminalLike {
  readonly cols: number;
  readonly rows: number;
  write(data: string): void;
  onData(listener: (data: string) => void): Disposable;
  onResize(listener: (size: { cols: number; rows: number }) => void): Disposable;
}

/** Where lines for Run in terminal come from (terminalLines.ts). */
export interface LineSource {
  // Hands over the function that types a line; returns the function that stops it.
  attach(type: (line: string) => void): () => void;
  // Lines that were not typed because the shell could not start in its folder.
  dropped(count: number): void;
}

/** The part of xterm.js's Terminal its copy and paste keys need. */
export interface ClipboardTerminal {
  hasSelection(): boolean;
  getSelection(): string;
  paste(text: string): void;
}

interface Clipboard {
  writeText(text: string): Promise<void>;
  readText(): Promise<string>;
}

/**
 * The terminal's own key rule, for xterm.js's attachCustomKeyEventHandler: Ctrl+Shift+C
 * copies the selection and Ctrl+Shift+V pastes, once (the web view's own paste of the
 * press is cancelled, or the text would arrive twice). The window's other Ctrl+Shift and
 * Ctrl+Alt shortcuts pass through to it, while plain Ctrl keys stay the shell's (Ctrl+C,
 * Ctrl+W...). Whether xterm.js handles the key.
 */
export function terminalKeys(
  terminal: ClipboardTerminal,
  clipboard: Clipboard,
): (event: KeyboardEvent) => boolean {
  return (event) => {
    if (!event.ctrlKey || !(event.shiftKey || event.altKey)) return true;
    const key = event.key.toLowerCase();
    const copy = event.shiftKey && !event.altKey && key === "c";
    const paste = event.shiftKey && !event.altKey && key === "v";
    if (!copy && !paste) return event.type !== "keydown";
    event.preventDefault();
    if (event.type !== "keydown") return false;
    if (copy) {
      if (terminal.hasSelection()) void clipboard.writeText(terminal.getSelection());
    } else {
      void clipboard.readText().then((text) => {
        terminal.paste(text);
      });
    }
    return false;
  };
}

/** The line a pane shows when its shell ends or cannot start. */
export function endLine(text: string): string {
  return `\r\n\u001b[2m${text}\u001b[0m\r\n`;
}

/**
 * Starts the user's shell in `cwd` for `terminal`: what it prints is written to the
 * terminal, what is typed goes to the shell, and a resize reaches it as columns and rows.
 * Lines from `lines` are typed once the shell has started (it reads them at its prompt),
 * and one that comes after the shell ended starts a new shell first, as the Mac's
 * TerminalView.run. Returns the function that ends it.
 */
export function connectTerminal(
  terminal: TerminalLike,
  bridge: Bridge,
  id: string,
  cwd: string | null,
  lines?: LineSource,
): () => void {
  let pty: Pty | null = null;
  let ended = false;
  let starting = false;
  let exited = false;
  // The shell could not start in its folder (gone), so nothing is typed there.
  let failed = false;
  let queued: string[] = [];
  const typed = terminal.onData((data) => {
    pty?.write(data);
  });
  const resized = terminal.onResize(({ cols, rows }) => {
    pty?.resize(cols, rows);
  });
  const start = () => {
    starting = true;
    exited = false;
    bridge
      .spawnPty(
        id,
        { cwd, cols: terminal.cols, rows: terminal.rows },
        {
          onOutput: (data) => {
            terminal.write(data);
          },
          onExit: (code) => {
            pty = null;
            exited = true;
            terminal.write(endLine(`The shell ended (${String(code)}).`));
          },
        },
      )
      .then(
        (started) => {
          starting = false;
          if (ended) {
            started.kill();
            return;
          }
          pty = started;
          for (const line of queued) started.write(line);
          queued = [];
        },
        (error: unknown) => {
          starting = false;
          failed = true;
          terminal.write(endLine(error instanceof Error ? error.message : String(error)));
          if (queued.length > 0) lines?.dropped(queued.length);
          queued = [];
        },
      );
  };
  const typeLine = (line: string) => {
    if (ended) return;
    if (failed) {
      lines?.dropped(1);
      return;
    }
    if (pty !== null) {
      pty.write(line);
      return;
    }
    queued.push(line);
    if (exited && !starting) {
      terminal.write("\r\n");
      start();
    }
  };
  start();
  const detach = lines?.attach(typeLine);
  return () => {
    ended = true;
    detach?.();
    typed.dispose();
    resized.dispose();
    pty?.kill();
    pty = null;
  };
}

/** The screen a terminal pane draws into: xterm.js's Terminal, or a fake in tests. */
export interface ScreenLike extends TerminalLike {
  open(parent: HTMLElement): void;
  dispose(): void;
}

/**
 * A terminal pane's shell and screen, kept apart from the pane's view (toolSessions.ts):
 * the view attaches the screen's element when it shows and detaches it when it goes, and
 * the shell starts with the first attach, once the screen can measure itself.
 */
export class TerminalSession<S extends ScreenLike = ScreenLike> {
  readonly host: HTMLElement;
  readonly screen: S;
  private stop: (() => void) | null = null;
  private ended = false;
  private readonly start: (screen: S) => () => void;

  constructor(screen: S, start: (screen: S) => () => void, host: HTMLElement) {
    this.screen = screen;
    this.start = start;
    this.host = host;
  }

  attach(parent: HTMLElement): void {
    if (this.ended) return;
    if (this.host.parentElement !== parent) parent.appendChild(this.host);
    if (this.stop !== null) return;
    this.screen.open(this.host);
    this.stop = this.start(this.screen);
  }

  /** Takes the screen off the page; the shell and what it printed stay. */
  detach(parent: HTMLElement): void {
    if (this.host.parentElement === parent) this.host.remove();
  }

  end(): void {
    if (this.ended) return;
    this.ended = true;
    this.stop?.();
    this.screen.dispose();
    this.host.remove();
  }
}
