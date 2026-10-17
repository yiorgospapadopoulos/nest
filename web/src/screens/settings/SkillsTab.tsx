import { useEffect, useState } from "react";
import type {
  AvailablePlugin,
  InstalledPlugin,
  Marketplace,
  PluginDetails,
} from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Pill } from "../../ui/bits.tsx";
import { Sheet } from "../../ui/Sheet.tsx";
import { Confirm } from "../pixies/Confirm.tsx";
import { NameSheet } from "../pixies/NameSheet.tsx";
import { Loading, Row, Section } from "./rows.tsx";

// A plugin's parts, as `claude plugin details` counts them.
const PARTS: { key: keyof NonNullable<PluginDetails["components"]>; label: string }[] = [
  { key: "skills", label: "Skills" },
  { key: "agents", label: "Agents" },
  { key: "hooks", label: "Hooks" },
  { key: "mcp_servers", label: "MCP servers" },
  { key: "lsp_servers", label: "LSP servers" },
];

type Ask = { remove: InstalledPlugin } | { drop: Marketplace };

/**
 * Claude Code's plugins with on/off and Remove, the standalone skills (read only), Browse,
 * and the marketplaces. Everything goes through `claude plugin` on the Mac (D104).
 */
export function SkillsTab() {
  const { state, actions } = useStore();
  const { plugins, skills, marketplaces } = state.settings;
  const [asking, setAsking] = useState<Ask | null>(null);
  const [adding, setAdding] = useState(false);
  const [browsing, setBrowsing] = useState(false);

  useEffect(() => {
    void actions.loadExtensions();
  }, [actions]);

  if (plugins === null || skills === null || marketplaces === null) {
    return <Loading title="Plugins" />;
  }
  return (
    <>
      <Section
        title="Plugins"
        tools={
          <button
            className="lnk"
            onClick={() => {
              setBrowsing(true);
            }}
          >
            Browse
          </button>
        }
      >
        {plugins.length === 0 && <div className="srow note">None installed</div>}
        {plugins.map((plugin) => (
          <div key={plugin.id} className="srow item">
            <span className="slab" id={`plugin-${plugin.id}`}>
              {plugin.name}
              <span className="hint">
                {plugin.version === null
                  ? plugin.marketplace
                  : `${plugin.marketplace}, ${plugin.version}`}
              </span>
            </span>
            <div className="sctl">
              <button
                className="sw"
                role="switch"
                aria-checked={plugin.enabled}
                aria-labelledby={`plugin-${plugin.id}`}
                onClick={() => void actions.setPluginEnabled(plugins, plugin, !plugin.enabled)}
              />
              <button
                className="b b-no"
                aria-label={`Remove ${plugin.name}`}
                onClick={() => {
                  setAsking({ remove: plugin });
                }}
              >
                Remove
              </button>
            </div>
          </div>
        ))}
      </Section>
      {skills.length > 0 && (
        <Section title="Skills">
          {skills.map((skill) => (
            <Row
              key={skill.path}
              label={
                <>
                  {skill.name}
                  {skill.description !== null && <span className="hint">{skill.description}</span>}
                </>
              }
            />
          ))}
        </Section>
      )}
      <Section title="Marketplaces">
        {marketplaces.map((m) => (
          <div key={m.name} className="srow item">
            <span className="slab">
              {m.name}
              {m.source !== null && <span className="hint">{m.source}</span>}
            </span>
            <button
              className="b b-no"
              aria-label={`Remove ${m.name}`}
              onClick={() => {
                setAsking({ drop: m });
              }}
            >
              Remove
            </button>
          </div>
        ))}
        <div className="srow">
          <button
            className="b"
            onClick={() => {
              setAdding(true);
            }}
          >
            Add marketplace
          </button>
        </div>
      </Section>
      {asking !== null && "remove" in asking && (
        <Confirm
          title={`Remove ${asking.remove.name}?`}
          about="Claude Code uninstalls it on your Mac."
          action="Remove"
          onConfirm={() => void actions.uninstallPlugin(asking.remove)}
          onClose={() => {
            setAsking(null);
          }}
        />
      )}
      {asking !== null && "drop" in asking && (
        <Confirm
          title={`Remove ${asking.drop.name}?`}
          about="Its plugins can no longer be installed from it."
          action="Remove"
          onConfirm={() => void actions.removeMarketplace(asking.drop)}
          onClose={() => {
            setAsking(null);
          }}
        />
      )}
      {adding && (
        <NameSheet
          title="Add marketplace"
          label="Source"
          empty="Type a URL, a path or a GitHub repository"
          initial=""
          action="Add"
          code
          onSave={(source) => {
            void actions.addMarketplace(source).then((done) => {
              if (done) setAdding(false);
            });
          }}
          onClose={() => {
            setAdding(false);
          }}
        />
      )}
      {browsing && (
        <Browse
          onClose={() => {
            setBrowsing(false);
          }}
        />
      )}
    </>
  );
}

/** The plugins the marketplaces offer; one opens its details, with Install. */
function Browse({ onClose }: { onClose: () => void }) {
  const { actions } = useStore();
  const [available, setAvailable] = useState<AvailablePlugin[] | null>(null);
  const [open, setOpen] = useState<AvailablePlugin | null>(null);
  // Installed here since the list loaded.
  const [added, setAdded] = useState<string[]>([]);

  useEffect(() => {
    let live = true;
    void actions.availablePlugins().then((found) => {
      if (live) setAvailable(found ?? []);
    });
    return () => {
      live = false;
    };
  }, [actions]);

  if (open !== null) {
    return (
      <Details
        plugin={open}
        onBack={() => {
          setOpen(null);
        }}
        onInstalled={() => {
          setAdded((before) => [...before, open.id]);
          setOpen(null);
        }}
      />
    );
  }
  return (
    <Sheet title="Browse plugins" onClose={onClose}>
      <div className="lgrp gl">
        {available === null && <div className="srow note">Loading...</div>}
        {available?.length === 0 && <div className="srow note">No plugins offered</div>}
        {available
          ?.map((p) => (added.includes(p.id) ? { ...p, installed: true } : p))
          .map((plugin) => (
            <div key={plugin.id} className="srow item">
              <span className="slab">
                {plugin.name}
                <span className="hint">{plugin.marketplace}</span>
              </span>
              <div className="sctl">
                {plugin.installed && <Pill tone="rev" label="Installed" />}
                <button
                  className="b"
                  aria-label={`Details of ${plugin.name}`}
                  onClick={() => {
                    setOpen(plugin);
                  }}
                >
                  Details
                </button>
              </div>
            </div>
          ))}
      </div>
    </Sheet>
  );
}

function Details({
  plugin,
  onBack,
  onInstalled,
}: {
  plugin: AvailablePlugin;
  onBack: () => void;
  onInstalled: () => void;
}) {
  const { actions } = useStore();
  const [details, setDetails] = useState<PluginDetails | null>(null);
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    let live = true;
    void actions.pluginDetails(plugin.id).then((found) => {
      if (live && found !== null) setDetails(found);
    });
    return () => {
      live = false;
    };
  }, [actions, plugin.id]);

  const parts = details?.components ?? null;
  return (
    <Sheet title={plugin.name} onClose={onBack}>
      <div className="lgrp gl">
        {plugin.description !== null && <div className="srow">{plugin.description}</div>}
        <Row label="Source">
          <span className="sval mono">{plugin.source}</span>
        </Row>
        {plugin.version !== null && (
          <Row label="Version">
            <span className="sval">{plugin.version}</span>
          </Row>
        )}
        {details === null && <div className="srow note">Loading...</div>}
        {parts !== null &&
          PARTS.filter(({ key }) => parts[key].count > 0).map(({ key, label }) => (
            <Row key={key} label={`${label} (${String(parts[key].count)})`}>
              <span className="sval">{parts[key].names.join(", ")}</span>
            </Row>
          ))}
        <div className="srow">
          {plugin.installed ? (
            <Pill tone="rev" label="Installed" />
          ) : (
            <button
              className="b b-pri"
              onClick={() => {
                setAsking(true);
              }}
            >
              Install
            </button>
          )}
        </div>
      </div>
      {asking && (
        <Confirm
          title={`Install ${plugin.name}?`}
          about="Plugins can run code on this Mac. Install only those you trust."
          action="Install"
          onConfirm={() =>
            void actions.installPlugin(plugin).then((done) => {
              if (done) onInstalled();
            })
          }
          onClose={() => {
            setAsking(false);
          }}
        />
      )}
    </Sheet>
  );
}
