import { useCallback, useEffect, useRef, useState } from "react";
import type { CodexMarketplace, CodexPlugin } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";

// Codex's own plugins and marketplaces (B97), as ConfigurationStore's: one list serves the
// installed rows and Browse.

export interface CodexState {
  plugins: CodexPlugin[] | null;
  marketplaces: CodexMarketplace[];
  busy: string[];
  search: (query: string) => void;
  install: (plugin: CodexPlugin) => void;
  uninstall: (plugin: CodexPlugin) => void;
  addMarketplace: (source: string) => Promise<boolean>;
  removeMarketplace: (name: string) => void;
}

/** Codex's plugins as last listed, the search they match, and the marketplaces. */
export function useCodexPlugins(): CodexState {
  const { actions } = useStore();
  const [plugins, setPlugins] = useState<CodexPlugin[] | null>(null);
  const [marketplaces, setMarketplaces] = useState<CodexMarketplace[]>([]);
  const [busy, setBusy] = useState<string[]>([]);
  // A later search wins over an earlier one still answering.
  const asked = useRef(0);

  const search = useCallback(
    (query: string) => {
      asked.current += 1;
      const mine = asked.current;
      void actions.codexPlugins(query).then((found) => {
        if (found !== null && mine === asked.current) setPlugins(found.plugins);
      });
    },
    [actions],
  );
  useEffect(() => {
    search("");
    void actions.codexMarketplaces().then((found) => {
      if (found !== null) setMarketplaces(found);
    });
  }, [actions, search]);

  const working = (key: string, call: () => Promise<void>) => {
    setBusy((before) => [...before, key]);
    void call().finally(() => {
      setBusy((before) => before.filter((k) => k !== key));
    });
  };
  return {
    plugins,
    marketplaces,
    busy,
    search,
    install: (plugin) => {
      working(plugin.id, async () => {
        const found = await actions.installCodexPlugin(plugin.id);
        if (found !== null) setPlugins(found.plugins);
      });
    },
    uninstall: (plugin) => {
      working(plugin.id, async () => {
        const found = await actions.uninstallCodexPlugin(plugin.id);
        if (found !== null) setPlugins(found.plugins);
      });
    },
    addMarketplace: async (source) => {
      const found = await actions.addCodexMarketplace(source);
      if (found === null) return false;
      setMarketplaces(found);
      return true;
    },
    removeMarketplace: (name) => {
      working(name, async () => {
        const found = await actions.removeCodexMarketplace(name);
        if (found !== null) setMarketplaces(found);
      });
    },
  };
}
