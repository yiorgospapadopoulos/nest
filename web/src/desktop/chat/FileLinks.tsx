import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useStore } from "../../store/context.ts";
import { useNamedFiles } from "../../ui/namedFiles.ts";
import { CopyTextContext, OpenFileContext, ReadFileContext } from "../../ui/openFile.ts";
import { loopbackOrigin } from "../bridge.ts";
import { useBridge } from "../context.ts";
import { FileSheet } from "./FileSheet.tsx";

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
 * Lets the messages inside open the files they name (B144): in the viewer for a chat the
 * daemon knows, which also shows the images they name, with the text editor one click away
 * on the daemon's own computer; in the text editor alone for a chat only Claude Code knows.
 */
export function FileLinks({
  folder,
  session = null,
  children,
}: {
  folder: string | null;
  session?: string | null;
  children: ReactNode;
}) {
  const bridge = useBridge();
  const { actions } = useStore();
  const local = useLocalDaemon();
  const named = useNamedFiles(session);
  const editor = useCallback(
    (path: string) => {
      if (folder === null) return;
      bridge.openTextFile(path, folder).catch(() => {
        actions.toast("File not found", "error");
      });
    },
    [bridge, actions, folder],
  );
  const editable = local && folder !== null;
  // In a pane of the Mac app the page cannot reach the clipboard itself.
  const copy = useCallback(
    async (text: string) => {
      await (bridge.pane?.({ kind: "copy", text }) ?? navigator.clipboard.writeText(text));
    },
    [bridge],
  );
  return (
    <OpenFileContext value={named.open ?? (editable ? editor : null)}>
      <CopyTextContext value={copy}>
        <ReadFileContext value={named.read}>
          {children}
          {named.viewing !== null && (
            <FileSheet
              source={named.viewing}
              onClose={named.close}
              onEditor={editable ? editor.bind(null, named.viewing.path) : undefined}
            />
          )}
        </ReadFileContext>
      </CopyTextContext>
    </OpenFileContext>
  );
}
