import { useEffect, useState } from "react";
import type {
  AvailablePlugin,
  InstalledPlugin,
  Marketplace,
  PluginDetails,
} from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { useContextMenu } from "../../ui/contextMenu.tsx";
import { Button, TextField, Toggle } from "../../ui/controls.tsx";
import { Badge, SettingsListRow, SettingsSection } from "../rows.tsx";
import { componentNames, componentSummary, matching } from "./plugins.ts";
import { ConfigSubRow, EmptyLine, Glyph, StatusLabel } from "./parts.tsx";
import { Confirm } from "../../sheets/Alert.tsx";
import { useSettingsChange } from "./util.ts";

// Claude's plugins in Settings > Configuration (B97, from B81's Extensions), as
// PluginLists.swift: the installed ones with their switch, Browse and Marketplaces.

/** Each installed plugin with its switch; removed from its context menu. */
export function ClaudePluginRows() {
  const { state, actions } = useStore();
  const plugins = state.settings.plugins;
  const [removing, setRemoving] = useState<InstalledPlugin | null>(null);
  useEffect(() => {
    void actions.loadExtensions();
  }, [actions]);
  return (
    <div>
      {plugins?.length === 0 && (
        <ConfigSubRow>
          <span className="dkc-dim">No plugins installed</span>
        </ConfigSubRow>
      )}
      {plugins?.map((plugin) => (
        <PluginRow
          key={plugin.id}
          plugin={plugin}
          onRemove={() => {
            setRemoving(plugin);
          }}
        />
      ))}
      {removing !== null && (
        <Confirm
          title={`Remove ${removing.name}?`}
          message="Claude Code uninstalls it. Agents stop using it when they next start."
          action="Remove"
          destructive
          onConfirm={() => void actions.uninstallPlugin(removing)}
          onClose={() => {
            setRemoving(null);
          }}
        />
      )}
    </div>
  );
}

function PluginRow({ plugin, onRemove }: { plugin: InstalledPlugin; onRemove: () => void }) {
  const { state, actions } = useStore();
  const menu = useContextMenu(plugin.name, () => [
    { title: `Remove ${plugin.name}`, onSelect: onRemove },
  ]);
  return (
    <ConfigSubRow onContextMenu={menu.onContextMenu}>
      <span className="dkc-name">
        <b>{plugin.name}</b>
        <span className="dkc-dim"> · {plugin.marketplace}</span>
      </span>
      <span className="dkc-fill dkc-dim">{plugin.description ?? ""}</span>
      <Toggle
        checked={plugin.enabled}
        label={plugin.name}
        onChange={(on) => {
          void actions.setPluginEnabled(state.settings.plugins ?? [], plugin, on);
        }}
      />
      {menu.menu}
    </ConfigSubRow>
  );
}

// How many rows Browse draws at a time: drawing every marketplace plugin made Settings lag.
const PAGE = 10;

/** Browse: the plugins the marketplaces offer, each with what it brings, and Install. */
export function BrowseSection() {
  const { actions } = useStore();
  const change = useSettingsChange();
  const [all, setAll] = useState<AvailablePlugin[] | null>(null);
  const [installed, setInstalled] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(PAGE);
  const [open, setOpen] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, PluginDetails>>({});
  const [installing, setInstalling] = useState<AvailablePlugin | null>(null);

  const load = () => {
    change("Could not list the marketplaces' plugins", async () => {
      const found = await actions.availablePlugins();
      if (found !== null) setAll(found);
    });
  };
  const toggle = (plugin: AvailablePlugin) => {
    if (open === plugin.id) {
      setOpen(null);
      return;
    }
    setOpen(plugin.id);
    if (details[plugin.id] !== undefined) return;
    void actions.pluginDetails(plugin.id).then((found) => {
      if (found !== null) setDetails((before) => ({ ...before, [plugin.id]: found }));
    });
  };

  const available =
    all === null
      ? []
      : matching(all, query).map((p) => (installed.includes(p.id) ? { ...p, installed: true } : p));
  return (
    <SettingsSection title="Browse" bare>
      {all === null ? (
        <Button kind="primary" onClick={load}>
          Browse plugins
        </Button>
      ) : (
        <div className="dkc-list">
          {all.length > 0 && (
            <TextField
              className="dkc-search"
              label="Search plugins"
              placeholder={`Search ${String(all.length)} plugins`}
              value={query}
              onChange={(text) => {
                setQuery(text);
                setShown(PAGE);
              }}
            />
          )}
          {all.length === 0 ? (
            <EmptyLine text="The marketplaces offer no plugins" />
          ) : (
            available.length === 0 && <EmptyLine text="No plugins match" />
          )}
          {available.slice(0, shown).map((plugin) => (
            <AvailableRow
              key={plugin.id}
              plugin={plugin}
              open={open === plugin.id}
              details={details[plugin.id] ?? null}
              onToggle={() => {
                toggle(plugin);
              }}
              onInstall={() => {
                setInstalling(plugin);
              }}
            />
          ))}
          {available.length > shown && (
            <Button
              kind="plain"
              className="dkc-more"
              onClick={() => {
                setShown(shown + PAGE);
              }}
            >
              {`Load more (${String(available.length - shown)} left)`}
            </Button>
          )}
        </div>
      )}
      {installing !== null && (
        <Confirm
          title={`Install ${installing.name}?`}
          message="Plugins can run code on this computer. Install only plugins from sources you trust."
          action="Install"
          onConfirm={() => {
            const plugin = installing;
            void actions.installPlugin(plugin).then((done) => {
              if (done) setInstalled((before) => [...before, plugin.id]);
            });
          }}
          onClose={() => {
            setInstalling(null);
          }}
        />
      )}
    </SettingsSection>
  );
}

function AvailableRow({
  plugin,
  open,
  details,
  onToggle,
  onInstall,
}: {
  plugin: AvailablePlugin;
  open: boolean;
  details: PluginDetails | null;
  onToggle: () => void;
  onInstall: () => void;
}) {
  const components = details?.components ?? null;
  const summary = components === null ? [] : componentSummary(components);
  return (
    <div>
      <SettingsListRow
        title={plugin.name}
        detail={[plugin.description, plugin.marketplace].filter((p) => p !== null).join(" · ")}
        leading={<Badge text={plugin.name.slice(0, 2).toUpperCase()} />}
        trailing={
          <>
            <Button kind="plain" onClick={onToggle}>
              {open ? "Hide details" : "Details"}
            </Button>
            {plugin.installed ? (
              <StatusLabel tone="review" label="Installed" />
            ) : (
              <Button onClick={onInstall}>Install</Button>
            )}
          </>
        }
      />
      {open && (
        <div className="dkc-details">
          {details === null ? (
            <Fireflies />
          ) : (
            <>
              {components === null ? (
                <p>Its contents show once it is installed</p>
              ) : (
                <>
                  <p>
                    {summary.length === 0 ? "Brings nothing Claude Code lists" : summary.join(", ")}
                  </p>
                  {componentNames(components).map((names) => (
                    <p key={names} className="mono dkc-dim">
                      {names}
                    </p>
                  ))}
                </>
              )}
              <p className="mono dkc-select">Source: {details.source}</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** Claude Code's marketplaces, each with Remove, then a field to add one. */
export function MarketplacesSection() {
  const { state, actions } = useStore();
  const [source, setSource] = useState("");
  const [removing, setRemoving] = useState<Marketplace | null>(null);
  const add = () => {
    const text = source.trim();
    if (text === "") return;
    void actions.addMarketplace(text).then((done) => {
      if (done) setSource("");
    });
  };
  return (
    <SettingsSection title="Marketplaces" bare>
      <div className="dkc-list">
        {(state.settings.marketplaces ?? []).map((marketplace) => (
          <SettingsListRow
            key={marketplace.name}
            title={marketplace.name}
            detail={marketplace.source}
            mono
            leading={<BoxBadge />}
            trailing={
              <Button
                kind="danger"
                onClick={() => {
                  setRemoving(marketplace);
                }}
              >
                Remove
              </Button>
            }
          />
        ))}
      </div>
      <AddSource value={source} onChange={setSource} onAdd={add} />
      {removing !== null && (
        <Confirm
          title={`Remove ${removing.name}?`}
          message="Its plugins can no longer be installed from it."
          action="Remove"
          destructive
          onConfirm={() => void actions.removeMarketplace(removing)}
          onClose={() => {
            setRemoving(null);
          }}
        />
      )}
    </SettingsSection>
  );
}

/** The field a marketplace is added with: Return or Add. */
export function AddSource({
  value,
  onChange,
  onAdd,
}: {
  value: string;
  onChange: (value: string) => void;
  onAdd: () => void;
}) {
  return (
    <form
      className="dkc-add"
      onSubmit={(event) => {
        event.preventDefault();
        onAdd();
      }}
    >
      <TextField
        label="Marketplace source"
        placeholder="URL, path or GitHub repo"
        value={value}
        onChange={onChange}
      />
      <Button type="submit" disabled={value.trim() === ""}>
        Add
      </Button>
    </form>
  );
}

/** The marketplace's badge: the box in the badge's place. */
export function BoxBadge() {
  return (
    <span className="dks-badge" aria-hidden="true">
      <Glyph name="box" />
    </span>
  );
}
