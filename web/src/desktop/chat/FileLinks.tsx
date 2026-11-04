import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useStore } from "../../store/context.ts";
import { OpenFileContext } from "../../ui/openFile.ts";
import { loopbackOrigin } from "../bridge.ts";
import { useBridge } from "../context.ts";

/** Whether the daemon runs on this computer, so that a chat's paths are paths here. */
function useLocalDaemon(): boolean {
  const bridge = useBridge();
  const [local, setLocal] = useState(false);
  useEffect(() => {
    let gone = false;
    if (bridge.native) {
      bridge
        .daemon()
        .then((found) => {
          if (!gone) setLocal(loopbackOrigin(found.base) !== null);
        })
        .catch(() => undefined);
    }
    return () => {
      gone = true;
    };
  }, [bridge]);
  return local;
}

/**
 * Lets the messages inside open the files they name, in the text editor. Only with a folder
 * for the chat, in the desktop app, and on the daemon's own computer: elsewhere they stay text.
 */
export function FileLinks({ folder, children }: { folder: string | null; children: ReactNode }) {
  const bridge = useBridge();
  const { actions } = useStore();
  const local = useLocalDaemon();
  const open = useCallback(
    (path: string) => {
      if (folder === null) return;
      bridge.openTextFile(path, folder).catch(() => {
        actions.toast("File not found", "error");
      });
    },
    [bridge, actions, folder],
  );
  return (
    <OpenFileContext value={local && folder !== null ? open : null}>{children}</OpenFileContext>
  );
}
