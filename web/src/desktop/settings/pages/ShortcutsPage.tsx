import { useEffect, useState, useSyncExternalStore } from "react";
import {
  changeMessage,
  SHORTCUT_GROUPS,
  SHORTCUTS,
  shortcuts as deviceShortcuts,
  shortcutText,
  type ShortcutAction,
  type ShortcutsStore,
} from "../../layout/shortcuts.ts";
import { Button } from "../../ui/controls.tsx";
import { SettingsRow, SettingsSection } from "../rows.tsx";
import "../parts1/parts1.css";

/**
 * Every command's keys by group, as the Mac's Keyboard shortcuts (B81): Change records the
 * next keys pressed in the window for that command, refused keys say why on the row, and
 * Restore defaults puts every command back. The choices are kept on this device.
 */
export function ShortcutsPage({ store = deviceShortcuts }: { store?: ShortcutsStore }) {
  useSyncExternalStore(store.subscribe, () => store.version);
  const [recording, setRecording] = useState<ShortcutAction | null>(null);
  const [refusal, setRefusal] = useState<{ action: ShortcutAction; message: string } | null>(null);

  // The next key press goes to the recorder before the window's shortcuts can act on it.
  useEffect(() => {
    if (recording === null) return;
    const onKey = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();
      const result = store.record(event, recording);
      if (result === null) return;
      const message = changeMessage(result.change, result.shortcut);
      if (message === null) setRecording(null);
      else setRefusal({ action: recording, message });
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
    };
  }, [recording, store]);

  return (
    <>
      {SHORTCUT_GROUPS.map((group) => (
        <SettingsSection key={group.title} title={group.title}>
          {group.actions.map((action) => {
            const on = recording === action;
            return (
              <SettingsRow key={action} label={SHORTCUTS[action].title}>
                {refusal?.action === action && (
                  <span className="dks-refused">{refusal.message}</span>
                )}
                <kbd className={on ? "dks-kbd recording" : "dks-kbd"}>
                  {on ? "Press keys" : shortcutText(store.shortcut(action))}
                </kbd>
                <Button
                  aria-label={on ? "Cancel" : `Change ${SHORTCUTS[action].title}`}
                  onClick={() => {
                    setRefusal(null);
                    setRecording(on ? null : action);
                  }}
                >
                  {on ? "Cancel" : "Change"}
                </Button>
              </SettingsRow>
            );
          })}
        </SettingsSection>
      ))}
      <div className="dks-restore">
        <Button
          disabled={!store.hasChanges}
          onClick={() => {
            setRecording(null);
            setRefusal(null);
            store.restoreDefaults();
          }}
        >
          Restore defaults
        </Button>
      </div>
    </>
  );
}
