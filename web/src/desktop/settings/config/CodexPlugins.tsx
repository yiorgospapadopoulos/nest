import { useState } from "react";
import type { CodexPlugin } from "../../../api/types.ts";
import { Button, TextField } from "../../ui/controls.tsx";
import { SettingsListRow } from "../rows.tsx";
import { AddSource, BoxBadge } from "./ClaudePlugins.tsx";
import type { CodexState } from "./codexState.ts";
import { ConfigSubRow, EmptyLine } from "./parts.tsx";

// Codex's own plugins and marketplaces (B97), as ConfigurationView.swift's CodexPluginRows,
// CodexBrowse and CodexMarketplaces.

function CodexPluginRow({ plugin, codex }: { plugin: CodexPlugin; codex: CodexState }) {
  const busy = codex.busy.includes(plugin.id);
  return (
    <ConfigSubRow>
      <span className="dkc-name">
        <b>{plugin.name}</b>
        <span className="dkc-dim"> · {plugin.marketplace}</span>
      </span>
      <span className="dkc-fill dkc-dim">{plugin.description ?? ""}</span>
      {plugin.installed ? (
        <Button
          kind="danger"
          disabled={busy}
          onClick={() => {
            codex.uninstall(plugin);
          }}
        >
          Remove
        </Button>
      ) : (
        <Button
          disabled={busy}
          onClick={() => {
            codex.install(plugin);
          }}
        >
          Install
        </Button>
      )}
    </ConfigSubRow>
  );
}

export function CodexPluginRows({ codex }: { codex: CodexState }) {
  const installed = (codex.plugins ?? []).filter((p) => p.installed);
  return (
    <div>
      {codex.plugins !== null && installed.length === 0 && (
        <ConfigSubRow>
          <span className="dkc-dim">No plugins of Codex&apos;s own</span>
        </ConfigSubRow>
      )}
      {installed.map((plugin) => (
        <CodexPluginRow key={plugin.id} plugin={plugin} codex={codex} />
      ))}
    </div>
  );
}

export function CodexBrowse({ codex }: { codex: CodexState }) {
  const [query, setQuery] = useState("");
  const offered = (codex.plugins ?? []).filter((p) => !p.installed);
  return (
    <div className="dkc-list">
      <TextField
        className="dkc-search"
        label="Search Codex's plugins"
        placeholder="Search Codex's plugins"
        value={query}
        onChange={(text) => {
          setQuery(text);
          codex.search(text);
        }}
      />
      {codex.plugins !== null && offered.length === 0 && (
        <EmptyLine text={query === "" ? "The marketplaces offer no plugins" : "No plugins match"} />
      )}
      {offered.map((plugin) => (
        <CodexPluginRow key={plugin.id} plugin={plugin} codex={codex} />
      ))}
    </div>
  );
}

export function CodexMarketplaces({ codex }: { codex: CodexState }) {
  const [source, setSource] = useState("");
  const add = () => {
    const text = source.trim();
    if (text === "") return;
    void codex.addMarketplace(text).then((done) => {
      if (done) setSource("");
    });
  };
  return (
    <div>
      <div className="dkc-list">
        {codex.marketplaces.map((marketplace) => (
          <SettingsListRow
            key={marketplace.name}
            title={marketplace.name}
            detail={marketplace.path}
            mono
            leading={<BoxBadge />}
            trailing={
              <Button
                kind="danger"
                disabled={codex.busy.includes(marketplace.name)}
                onClick={() => {
                  codex.removeMarketplace(marketplace.name);
                }}
              >
                Remove
              </Button>
            }
          />
        ))}
      </div>
      <AddSource value={source} onChange={setSource} onAdd={add} />
    </div>
  );
}
