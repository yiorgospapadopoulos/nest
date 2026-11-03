import type { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useRef } from "react";
import { useStore } from "../../store/context.ts";
import { useBridge } from "../context.ts";
import type { ToolPane } from "../layout/tools.ts";
import { GONE_MESSAGE } from "./frame/terminal.ts";
import { sessionFor, themeOf } from "./terminals.ts";

/**
 * A terminal pane (B117): the user's login shell in the pane's folder through the Tauri
 * side's pty, drawn by xterm.js with its DOM renderer (WebGL can fall back to software on
 * Linux). The shell and its screen live on while the pane is out of view (another tab or
 * view), as on the Mac; the view fits the screen to the pane and tells the shell the size.
 */
export function TerminalPane({ pane, focused }: { pane: ToolPane; focused: boolean }) {
  const bridge = useBridge();
  const { actions } = useStore();
  const box = useRef<HTMLDivElement>(null);
  const term = useRef<Terminal | null>(null);
  const { id, folder } = pane;

  useEffect(() => {
    const element = box.current;
    if (element === null) return;
    const session = sessionFor(id, folder, bridge, element);
    const { fit } = session;
    session.gone = () => {
      actions.toast(GONE_MESSAGE, "error");
    };
    session.attach(element);
    const terminal = session.screen;
    fit.fit();
    term.current = terminal;
    const observer = new ResizeObserver(() => {
      if (element.clientWidth > 0 && element.clientHeight > 0) fit.fit();
    });
    observer.observe(element);
    const scheme = window.matchMedia("(prefers-color-scheme: dark)");
    const retheme = () => {
      terminal.options.theme = themeOf(element);
    };
    retheme();
    // The theme can change with the system's or with Settings > Appearance.
    scheme.addEventListener("change", retheme);
    const attributes = new MutationObserver(retheme);
    attributes.observe(document.documentElement, { attributeFilter: ["data-theme"] });
    return () => {
      observer.disconnect();
      attributes.disconnect();
      scheme.removeEventListener("change", retheme);
      session.detach(element);
      term.current = null;
    };
  }, [bridge, actions, id, folder]);

  useEffect(() => {
    if (focused) term.current?.focus();
  }, [focused]);

  return <div ref={box} className="dk-term" aria-label="Terminal" />;
}
