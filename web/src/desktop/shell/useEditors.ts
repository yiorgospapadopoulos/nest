import { useCallback, useEffect, useState } from "react";
import type { Api } from "../../api/client.ts";
import type { EditorId, Editors } from "../../api/types.ts";

/**
 * The editors installed on the daemon's computer (B152), read at start and again whenever
 * the window comes back to the front, so one installed meanwhile shows in Open in.
 */
export function useEditors(api: Api): {
  editors: Editors | null;
  setDefaultEditor: (editor: EditorId | null) => Promise<void>;
} {
  const [editors, setEditors] = useState<Editors | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => {
      api.editors().then(
        (found) => {
          if (live) setEditors(found);
        },
        () => undefined,
      );
    };
    load();
    window.addEventListener("focus", load);
    return () => {
      live = false;
      window.removeEventListener("focus", load);
    };
  }, [api]);
  const setDefaultEditor = useCallback(
    async (editor: EditorId | null) => {
      setEditors(await api.setDefaultEditor(editor));
    },
    [api],
  );
  return { editors, setDefaultEditor };
}
