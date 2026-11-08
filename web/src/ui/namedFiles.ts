import { useCallback, useState } from "react";
import { useStore } from "../store/context.ts";
import type { FileSource } from "./useFileView.tsx";
import type { OpenFile, ReadFile } from "./openFile.ts";

export type NamedSource = Extract<FileSource, { kind: "named" }>;

/** For a chat's messages: what opens a file they name in the viewer, and reads one (B144). */
export function useNamedFiles(session: string | null): {
  viewing: NamedSource | null;
  open: OpenFile | null;
  read: ReadFile | null;
  close: () => void;
} {
  const { actions } = useStore();
  const [viewing, setViewing] = useState<NamedSource | null>(null);
  const open = useCallback(
    (path: string, line: number | null) => {
      if (session !== null) setViewing({ kind: "named", session, path, line });
    },
    [session],
  );
  const read = useCallback(
    async (path: string) => {
      if (session === null) return null;
      const found = await actions.namedFile(session, path);
      return found instanceof Blob ? found : null;
    },
    [actions, session],
  );
  const close = useCallback(() => {
    setViewing(null);
  }, []);
  return {
    viewing,
    open: session === null ? null : open,
    read: session === null ? null : read,
    close,
  };
}
