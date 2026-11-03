// Every terminal pane's shell and screen, by pane id (toolSessions.ts), made with xterm.js.
import { FitAddon } from "@xterm/addon-fit";
import { Terminal, type ITheme } from "@xterm/xterm";
import { ptyId, type Bridge } from "../bridge.ts";
import { linesFor } from "./terminalLines.ts";
import { connectTerminal, TerminalSession, terminalKeys } from "./terminalSession.ts";
import { ToolSessions } from "./toolSessions.ts";

/** The terminal's colours from the window's tokens, so it follows light and dark. */
export function themeOf(element: Element): ITheme {
  const style = getComputedStyle(element);
  const token = (name: string) => style.getPropertyValue(name).trim();
  return {
    background: token("--bg"),
    foreground: token("--t1"),
    cursor: token("--t1"),
    cursorAccent: token("--bg"),
    selectionBackground: token("--sel") || token("--fill"),
  };
}

class PaneTerminal extends TerminalSession<Terminal> {
  fit = new FitAddon();
  // Says that the shell cannot start in its folder, through the view showing it now.
  gone: () => void = () => undefined;
}

export const terminals = new ToolSessions<PaneTerminal>();

export function sessionFor(id: string, folder: string | null, bridge: Bridge, element: Element) {
  return terminals.session(id, () => {
    const screen = new Terminal({
      fontFamily: getComputedStyle(element).getPropertyValue("--mono").trim() || "monospace",
      fontSize: 12,
      lineHeight: 1.2,
      cursorBlink: true,
      scrollback: 5000,
      theme: themeOf(element),
    });
    screen.attachCustomKeyEventHandler(terminalKeys(screen, navigator.clipboard));
    const host = document.createElement("div");
    host.className = "dk-term-host";
    const made: PaneTerminal = new PaneTerminal(
      screen,
      (s) =>
        connectTerminal(
          s,
          bridge,
          ptyId(id),
          folder,
          linesFor(id, () => {
            made.gone();
          }),
        ),
      host,
    );
    screen.loadAddon(made.fit);
    return made;
  });
}
