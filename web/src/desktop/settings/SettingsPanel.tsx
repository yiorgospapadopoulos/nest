import { useEffect, useState } from "react";
import { useShell } from "../shell/context.ts";
import { SettingsView } from "./SettingsView.tsx";

/** Gives the keyboard back on closing: the field that had it, else the focused pane's composer. */
function useFocusBack() {
  // Read while rendering, before the chats behind the panel go inert.
  const [before] = useState(() => document.activeElement);
  useEffect(() => {
    return () => {
      const field =
        before instanceof HTMLTextAreaElement || before instanceof HTMLInputElement ? before : null;
      const target = field?.isConnected
        ? field
        : document.querySelector<HTMLTextAreaElement>(
            '.dk-pane.focused textarea[aria-label="Message"]',
          );
      target?.focus({ preventScroll: true });
    };
  }, [before]);
}

/**
 * Settings over the dimmed chats (B118), as the Mac's SettingsPanel: what is behind stays
 * mounted, so chats, terminals and panes keep their state. The X, Esc, Ctrl+W or a press on
 * the dim closes it; the sheets of its pages sit over all of it.
 */
export function SettingsPanel() {
  const shell = useShell();
  useFocusBack();
  return (
    <div
      className="dks-scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) shell.closeSettings();
      }}
    >
      <div className="dks-panel">
        <SettingsView />
      </div>
    </div>
  );
}
