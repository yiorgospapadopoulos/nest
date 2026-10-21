import { useEffect, useState } from "react";
import type { CodexMarketplace, CodexPlugin, CodexPlugins } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Sheet } from "../../ui/Sheet.tsx";

interface Props {
  // The installed list is shown.
  open: boolean;
  browsing: boolean;
  markets: boolean;
  onCloseBrowse: () => void;
  onCloseMarkets: () => void;
}

/**
 * Codex's own plugins in its Configuration section (B97, B102 item 31): the installed ones
 * with Remove, Browse to search and install, and Codex's marketplaces.
 */
export function CodexPluginsPart({
  open,
  browsing,
  markets,
  onCloseBrowse,
  onCloseMarkets,
}: Props) {
  const { actions } = useStore();
  const [listed, setListed] = useState<CodexPlugins | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let live = true;
    void actions.codexPlugins("").then((found) => {
      if (live && found !== null) setListed(found);
    });
    return () => {
      live = false;
    };
  }, [actions, open]);

  // An install or removal answers with every plugin; the lists follow it.
  const change = (plugin: CodexPlugin): Promise<CodexPlugins | null> => {
    setBusy(plugin.id);
    const call = plugin.installed
      ? actions.uninstallCodexPlugin(plugin.id)
      : actions.installCodexPlugin(plugin.id);
    return call.then((found) => {
      setBusy(null);
      if (found !== null) setListed(found);
      return found;
    });
  };

  const installed = listed?.plugins.filter((p) => p.installed) ?? [];
  return (
    <>
      {open && listed === null && <div className="srow note sub">Loading...</div>}
      {open && listed !== null && installed.length === 0 && (
        <div className="srow note sub">No plugins of Codex's own</div>
      )}
      {open &&
        installed.map((plugin) => (
          <CodexPluginRow
            key={plugin.id}
            plugin={plugin}
            busy={busy === plugin.id}
            onChange={() => void change(plugin)}
          />
        ))}
      {browsing && <CodexBrowse busy={busy} onChange={change} onClose={onCloseBrowse} />}
      {markets && <CodexMarketplaces onClose={onCloseMarkets} />}
    </>
  );
}

function CodexPluginRow({
  plugin,
  busy,
  onChange,
}: {
  plugin: CodexPlugin;
  busy: boolean;
  onChange: () => void;
}) {
  return (
    <div className="srow item sub">
      <span className="slab">
        {plugin.name}
        <span className="hint">
          {plugin.description === null
            ? plugin.marketplace
            : `${plugin.marketplace} · ${plugin.description}`}
        </span>
      </span>
      <button
        className="b"
        aria-label={`${plugin.installed ? "Remove" : "Install"} ${plugin.name}`}
        disabled={busy}
        onClick={onChange}
      >
        {plugin.installed ? "Remove" : "Install"}
      </button>
    </div>
  );
}

/** The plugins Codex's marketplaces offer, searched as the user types. */
function CodexBrowse({
  busy,
  onChange,
  onClose,
}: {
  busy: string | null;
  onChange: (plugin: CodexPlugin) => Promise<CodexPlugins | null>;
  onClose: () => void;
}) {
  const { actions } = useStore();
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<CodexPlugins | null>(null);

  useEffect(() => {
    let live = true;
    void actions.codexPlugins(query).then((list) => {
      if (live && list !== null) setFound(list);
    });
    return () => {
      live = false;
    };
  }, [actions, query]);

  const offered = found?.plugins.filter((p) => !p.installed) ?? [];
  return (
    <Sheet title="Browse Codex's plugins" onClose={onClose}>
      <input
        className="cfg-search"
        type="search"
        aria-label="Search Codex's plugins"
        placeholder="Search Codex's plugins"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
      />
      <div className="lgrp gl">
        {found === null && <div className="srow note">Loading...</div>}
        {found !== null && offered.length === 0 && (
          <div className="srow note">
            {query === "" ? "The marketplaces offer no plugins" : "No plugins match"}
          </div>
        )}
        {offered.map((plugin) => (
          <CodexPluginRow
            key={plugin.id}
            plugin={plugin}
            busy={busy === plugin.id}
            onChange={() =>
              void onChange(plugin).then((list) => {
                if (list !== null) setFound(list);
              })
            }
          />
        ))}
      </div>
    </Sheet>
  );
}

/** Codex's marketplaces, with Remove and a field to add one. */
function CodexMarketplaces({ onClose }: { onClose: () => void }) {
  const { actions } = useStore();
  const [markets, setMarkets] = useState<CodexMarketplace[] | null>(null);
  const [source, setSource] = useState("");

  useEffect(() => {
    let live = true;
    void actions.codexMarketplaces().then((found) => {
      if (live && found !== null) setMarkets(found);
    });
    return () => {
      live = false;
    };
  }, [actions]);

  const add = async () => {
    const found = await actions.addCodexMarketplace(source.trim());
    if (found === null) return;
    setMarkets(found);
    setSource("");
  };
  const remove = async (name: string) => {
    const found = await actions.removeCodexMarketplace(name);
    if (found !== null) setMarkets(found);
  };

  return (
    <Sheet title="Codex's marketplaces" onClose={onClose}>
      <div className="lgrp gl">
        {markets === null && <div className="srow note">Loading...</div>}
        {markets?.map((m) => (
          <div key={m.name} className="srow item">
            <span className="slab">
              {m.name}
              {m.path !== null && <span className="hint mono">{m.path}</span>}
            </span>
            <button
              className="b"
              aria-label={`Remove ${m.name}`}
              onClick={() => void remove(m.name)}
            >
              Remove
            </button>
          </div>
        ))}
        <div className="srow">
          <input
            className="cfg-search"
            aria-label="Marketplace source"
            placeholder="URL, path or GitHub repo"
            autoCapitalize="off"
            autoCorrect="off"
            value={source}
            onChange={(event) => {
              setSource(event.target.value);
            }}
          />
          <button className="b" disabled={source.trim() === ""} onClick={() => void add()}>
            Add
          </button>
        </div>
      </div>
    </Sheet>
  );
}
