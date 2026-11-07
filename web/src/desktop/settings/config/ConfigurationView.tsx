import { useEffect, useState, type ReactNode } from "react";
import type {
  ConfigurationPage,
  CopyPreview,
  EngineItem,
  EngineSection,
  SharedServer,
  SkillItem,
} from "../../../api/types.ts";
import {
  copyTitle,
  engineLine,
  fixedCaption,
  INTRO,
  itemDetail,
  itemTitle,
  missingNote,
  NEW_SERVER,
  rulesElsewhere,
  serverEngines,
  serverForm,
  showsCodexSwitch,
  shownSkills,
  skillDetail,
  skillsToggle,
  skillTag,
} from "../../../screens/settings/configText.ts";
import { useStore } from "../../../store/context.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Icon } from "../../../ui/Icon.tsx";
import { EngineMark } from "../../shell/frame/marks.tsx";
import { useContextMenu } from "../../ui/contextMenu.tsx";
import { Button, Toggle } from "../../ui/controls.tsx";
import { Failure } from "../rows.tsx";
import { BrowseSection, ClaudePluginRows, MarketplacesSection } from "./ClaudePlugins.tsx";
import { CodexBrowse, CodexMarketplaces, CodexPluginRows } from "./CodexPlugins.tsx";
import { useCodexPlugins } from "./codexState.ts";
import { ConnectorsList } from "./Connectors.tsx";
import { CopySheet, type CopyDone } from "./CopySheet.tsx";
import { useConfigModals } from "./modals.ts";
import {
  ConfigChip,
  ConfigIcon,
  ConfigLabel,
  ConfigRow,
  ConfigSubRow,
  FoldChevron,
  RowText,
} from "./parts.tsx";
import { Confirm } from "../../sheets/Alert.tsx";
import { fileName, shortPath, useOpenPath, useSettingsChange } from "./util.ts";

const SHARED_SWITCHES = [
  ["instructions", "Instructions"],
  ["skills", "Skills"],
  ["mcp_servers", "MCP servers"],
] as const;

/**
 * Settings > Configuration (B97), as the Mac's ConfigurationView: what the agents read.
 * Shared instructions, skills and MCP servers on top, then a fold-open section per signed-in
 * engine, one open at a time. The engines' own files are the only source of truth; the page
 * follows them live.
 */
export function ConfigurationView() {
  const { state, actions } = useStore();
  const page = state.settings.configuration;
  // The engine open; undefined until the user opens or closes one, while the first opens.
  const [chosen, setChosen] = useState<string | null | undefined>(undefined);
  const [copy, setCopy] = useState<{ engine: EngineSection; preview: CopyPreview } | null>(null);
  const [done, setDone] = useState<CopyDone | null>(null);
  const change = useSettingsChange();
  const local = state.local.list;
  const signInOptional = local !== null && (local.local_only || local.models.length > 0);

  useEffect(() => {
    void actions.loadConfiguration();
  }, [actions]);

  // An engine signed out meanwhile closes its section.
  const openEngine =
    chosen === undefined
      ? (page?.engines[0]?.id ?? null)
      : page?.engines.some((e) => e.id === chosen) === true
        ? chosen
        : null;

  const toggleEngine = (id: string) => {
    const next = openEngine === id ? null : id;
    setChosen(next);
    // Folding the engine closes its popup.
    if (copy !== null && copy.engine.id !== next) setCopy(null);
  };
  const startCopy = (engine: EngineSection) => {
    change("Could not read what the copy would do", async () => {
      const preview = await actions.copyPreview(engine.id);
      if (preview === null) return;
      setDone(null);
      setCopy({ engine, preview });
    });
  };

  return (
    <div className="dkc-page">
      <p className="dkc-intro">{INTRO}</p>
      {page === null ? (
        <div className="dkc-loading">
          <Fireflies />
        </div>
      ) : (
        <>
          <SharedSection page={page} />
          <ConfigLabel text="Engines" />
          {page.engines.map((engine) => (
            <EngineBox
              key={engine.id}
              engine={engine}
              open={openEngine === engine.id}
              done={done?.engine === engine.id ? done : null}
              onToggle={() => {
                toggleEngine(engine.id);
              }}
              onCopy={() => {
                startCopy(engine);
              }}
              onUndone={() => {
                setDone(null);
              }}
            />
          ))}
        </>
      )}
      {!signInOptional && (
        <p className="dkc-foot">
          Other engines appear here once you sign in to them under Accounts.
        </p>
      )}
      {copy !== null && (
        <CopySheet
          engine={copy.engine}
          preview={copy.preview}
          onDone={(finished) => {
            setDone(finished);
            setCopy(null);
          }}
          onClose={() => {
            setCopy(null);
          }}
        />
      )}
    </div>
  );
}

function SharedSection({ page }: { page: ConfigurationPage }) {
  const modals = useConfigModals();
  const { instructions, skills, mcp_servers: servers } = page.shared;
  const holder = rulesElsewhere(page);
  const codexIn = page.engines.some((e) => e.id === "codex");
  const [showAll, setShowAll] = useState(false);
  const toggle = skillsToggle(skills.items.length, showAll);
  const openPath = useOpenPath();
  return (
    <>
      <ConfigLabel text="Shared" />
      <ConfigRow>
        <ConfigIcon name="doc" />
        <RowText
          title={
            <>
              Instructions <span className="dkc-file">{fileName(instructions.path)}</span>
            </>
          }
        >
          {holder === null
            ? "Read by Codex as it is; Claude's CLAUDE.md imports it. "
            : `Empty. Your rules are in ${holder.name}'s CLAUDE.md; copy them here to share them with every engine. `}
          <span className="mono">{shortPath(instructions.path)}</span>
        </RowText>
        <Button
          onClick={() => {
            modals.edit({
              path: instructions.path,
              title: "Instructions",
              note: "used by Claude and Codex",
            });
          }}
        >
          Edit
        </Button>
      </ConfigRow>
      <ConfigRow>
        <ConfigIcon name="star" />
        <RowText
          title={
            <>
              Skills <span className="dkc-count">{skills.items.length}</span>
            </>
          }
        >
          One folder for every engine. <span className="mono">{shortPath(skills.folder)}</span>
        </RowText>
        <Button
          onClick={() => {
            modals.form({ skill: { repo: null, folder: skills.folder } });
          }}
        >
          New skill
        </Button>
        {openPath !== null && (
          <Button
            onClick={() => {
              openPath(skills.folder, false, true);
            }}
          >
            Open folder
          </Button>
        )}
      </ConfigRow>
      {shownSkills(skills.items, showAll).map((skill) => (
        <SkillRow key={skill.path} skill={skill} codexIn={codexIn} />
      ))}
      {toggle !== null && (
        <ConfigSubRow>
          <button
            type="button"
            className="dkc-toggle"
            onClick={() => {
              setShowAll(!showAll);
            }}
          >
            {toggle}
          </button>
        </ConfigSubRow>
      )}
      <ConfigRow>
        <ConfigIcon name="server" />
        <RowText
          title={
            <>
              MCP servers <span className="dkc-count">{servers.length}</span>
            </>
          }
        >
          Set up once; Nest writes each into every engine&apos;s own config.
        </RowText>
        <Button
          onClick={() => {
            modals.form({ server: NEW_SERVER, isNew: true, repo: null });
          }}
        >
          Add server
        </Button>
      </ConfigRow>
      {servers.map((server) => (
        <ServerRow key={server.name} server={server} />
      ))}
    </>
  );
}

function SkillRow({ skill, codexIn }: { skill: SkillItem; codexIn: boolean }) {
  const { actions } = useStore();
  const modals = useConfigModals();
  const [removing, setRemoving] = useState(false);
  const [busy, setBusy] = useState(false);
  const openPath = useOpenPath();
  const menu = useContextMenu(skill.name, () => [
    ...(openPath === null
      ? []
      : [
          {
            title: "Show in Files",
            onSelect: () => {
              openPath(skill.path, true);
            },
          },
        ]),
    ...(skill.source === "yours"
      ? [
          {
            title: `Remove ${skill.name}`,
            onSelect: () => {
              setRemoving(true);
            },
          },
        ]
      : []),
  ]);
  const enabled = skill.codex_enabled === true;
  return (
    <ConfigSubRow onContextMenu={menu.onContextMenu}>
      <b className="dkc-name">{skill.name}</b>
      <span className="dkc-fill dkc-dim">{skillDetail(skill)}</span>
      {codexIn && skill.codex_error !== null && (
        <ConfigChip text="not loaded by Codex" help={skill.codex_error} />
      )}
      <ConfigChip text={skillTag(skill)} />
      {codexIn && showsCodexSwitch(skill) && (
        <span className="dkc-codex">
          <span className="dkc-dim">Codex</span>
          <Toggle
            checked={enabled}
            label={`Load ${skill.name} in Codex`}
            onChange={(on) => void actions.setCodexSkill(skill.name, on)}
          />
        </span>
      )}
      {skill.source === "engine_only" ? (
        <Button
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void actions.makeSkillShared(skill.name).finally(() => {
              setBusy(false);
            });
          }}
        >
          Make shared
        </Button>
      ) : skill.read_only ? (
        <span className="dkc-dim">read only</span>
      ) : (
        <Button
          onClick={() => {
            modals.edit({ path: skill.path, title: skill.name, note: "skill" });
          }}
        >
          Edit
        </Button>
      )}
      {menu.menu}
      {removing && (
        <Confirm
          title={`Remove ${skill.name}?`}
          message="Its folder is removed from the shared skills, for every engine."
          action="Remove"
          destructive
          onConfirm={() => void actions.deleteSkill(skill.name)}
          onClose={() => {
            setRemoving(false);
          }}
        />
      )}
    </ConfigSubRow>
  );
}

function ServerRow({ server }: { server: SharedServer }) {
  const { actions } = useStore();
  const modals = useConfigModals();
  return (
    <ConfigSubRow>
      <b className="dkc-name">{server.name}</b>
      <span className="dkc-fill dkc-dim mono dkc-mid">{server.summary}</span>
      {server.convertible ? (
        serverEngines(server).map((engine) => <ConfigChip key={engine} text={engine} />)
      ) : (
        <>
          <ConfigChip text="Claude only" help={server.reason ?? "Codex cannot use this server"} />
          {server.reason !== null && <span className="dkc-dim dkc-clip">{server.reason}</span>}
        </>
      )}
      <Button
        onClick={() => {
          void actions.mcpServer(server.name).then((spec) => {
            if (spec !== null) {
              modals.form({ server: serverForm(server.name, spec), isNew: false, repo: null });
            }
          });
        }}
      >
        Edit
      </Button>
    </ConfigSubRow>
  );
}

interface EngineProps {
  engine: EngineSection;
  open: boolean;
  done: CopyDone | null;
  onToggle: () => void;
  onCopy: () => void;
  onUndone: () => void;
}

function EngineBox({ engine, open, done, onToggle, onCopy, onUndone }: EngineProps) {
  const { actions } = useStore();
  const missing = missingNote(engine.missing_from_shared);
  const note = missing ?? (done === null ? null : `Shared matches ${engine.name}`);
  return (
    <section className="dkc-engine" aria-label={engine.name}>
      <div className="dkc-engine-h">
        <button
          type="button"
          className="dkc-engine-t"
          aria-expanded={open}
          aria-label={`${engine.name}, ${engine.account ?? ""}`}
          onClick={onToggle}
        >
          <FoldChevron open={open} />
          <EngineMark provider={engine.id} size={15} />
          <b>{engine.name}</b>
          {engine.account !== null && <span className="dkc-dim">{engine.account}</span>}
        </button>
        {open && missing !== null && (
          <Button kind="primary" onClick={onCopy}>
            {copyTitle(engine.name)}
          </Button>
        )}
      </div>
      {open && note !== null && <p className="dkc-engine-note">{note}</p>}
      {open && (
        <div className="dkc-engine-b">
          {done !== null && (
            <div className="dkc-done" role="status">
              <Icon name="check" />
              <span>{done.summary}</span>
              <Button
                onClick={() =>
                  void actions.undoCopy(done.undoId).then((undone) => {
                    if (undone) onUndone();
                  })
                }
              >
                Undo
              </Button>
            </div>
          )}
          <EngineLine engine={engine} />
          <UsesShared engine={engine} />
          {engine.items.map((item) => (
            <EngineItemRow key={item.kind} engine={engine} item={item} />
          ))}
        </div>
      )}
    </section>
  );
}

/** The version Nest brings, a CLI found on this computer, and the config folder in use. */
function EngineLine({ engine }: { engine: EngineSection }) {
  const { state, actions } = useStore();
  const [asking, setAsking] = useState(false);
  const install = state.settings.install;
  const found = engine.standalone;
  return (
    <>
      <ConfigRow>
        <RowText
          title={
            <>
              Engine <span className="dkc-dim dkc-plain">{engineLine(engine)}</span>
            </>
          }
        >
          <span className="mono">{shortPath(engine.config_folder)}</span>
        </RowText>
        {found !== null ? (
          <span className="dkc-standalone">
            Also on this computer: {shortPath(found.path)}
            {found.version === null ? "" : ` ${found.version}`}
          </span>
        ) : (
          engine.id === "claude" &&
          (install?.state === "running" ? (
            <span className="dkc-installing">
              <Fireflies />
              {install.message ?? "Installing"}
            </span>
          ) : (
            <Button
              kind="plain"
              onClick={() => {
                setAsking(true);
              }}
            >
              Install Claude Code
            </Button>
          ))
        )}
      </ConfigRow>
      {engine.id === "claude" && install?.state === "failed" && (
        <Failure text={`Installing failed: ${install.message ?? "no reason given"}`} />
      )}
      {asking && (
        <Confirm
          title="Install Claude Code?"
          message="Nest runs Anthropic's installer from claude.ai/install.sh, so claude also works in a terminal."
          action="Install"
          onConfirm={() => void actions.installClaudeCode()}
          onClose={() => {
            setAsking(false);
          }}
        />
      )}
    </>
  );
}

function UsesShared({ engine }: { engine: EngineSection }) {
  const { actions } = useStore();
  const [busy, setBusy] = useState<string[]>([]);
  const captions = SHARED_SWITCHES.flatMap(([item]) =>
    engine.uses_shared[item].fixed ? [fixedCaption(engine.id, item)] : [],
  ).filter((caption) => caption !== null);
  return (
    <ConfigRow>
      <span className="dkc-text">
        <span className="dkc-uses">
          <b>Uses shared</b>
          {SHARED_SWITCHES.map(([item, title]) => {
            const value = engine.uses_shared[item];
            return (
              <span key={item} className="dkc-use" title={fixedCaption(engine.id, item) ?? ""}>
                <Toggle
                  checked={value.on}
                  label={`${engine.name} uses shared ${title}`}
                  disabled={value.fixed || busy.includes(item)}
                  onChange={(on) => {
                    setBusy((before) => [...before, item]);
                    void actions.setUsesShared(engine.id, item, on).finally(() => {
                      setBusy((before) => before.filter((b) => b !== item));
                    });
                  }}
                />
                <span className="dkc-dim2">{title}</span>
              </span>
            );
          })}
        </span>
        {captions.length > 0 && <span className="dkc-line">{`${captions.join(". ")}.`}</span>}
      </span>
    </ConfigRow>
  );
}

/**
 * One of the engine's own items: plugins and connectors fold open in place; a file opens
 * in the editor.
 */
function EngineItemRow({ engine, item }: { engine: EngineSection; item: EngineItem }) {
  if (item.kind === "plugins") {
    return engine.id === "claude" ? (
      <ClaudePluginsItem engine={engine} item={item} />
    ) : (
      <CodexPluginsItem engine={engine} item={item} />
    );
  }
  return <FileItem engine={engine} item={item} />;
}

function ItemTitle({ engine, item }: { engine: EngineSection; item: EngineItem }) {
  const detail = itemDetail(item, engine);
  return (
    <span className="dkc-item-t">
      <b>{itemTitle(item.kind)}</b>
      {detail !== null && <span className="dkc-dim">{detail}</span>}
    </span>
  );
}

function FoldTitle({
  open,
  onToggle,
  engine,
  item,
}: {
  open: boolean;
  onToggle: () => void;
  engine: EngineSection;
  item: EngineItem;
}) {
  return (
    <button type="button" className="dkc-item-fold" aria-expanded={open} onClick={onToggle}>
      <FoldChevron open={open} />
      <ItemTitle engine={engine} item={item} />
    </button>
  );
}

function FileItem({ engine, item }: { engine: EngineSection; item: EngineItem }) {
  const modals = useConfigModals();
  const [open, setOpen] = useState(false);
  const connectors = item.kind === "connectors";
  const path = item.path;
  const openPath = useOpenPath();
  return (
    <>
      <div className="dkc-item">
        {connectors ? (
          <FoldTitle
            open={open}
            onToggle={() => {
              setOpen(!open);
            }}
            engine={engine}
            item={item}
          />
        ) : (
          <>
            <span className="dkc-item-gap" />
            <ItemTitle engine={engine} item={item} />
          </>
        )}
        <span className="dkc-fill" />
        {connectors && <span className="dkc-dim">Claude only</span>}
        {path !== null && <span className="dkc-dim mono dkc-mid">{shortPath(path)}</span>}
        {path !== null && !item.folder && (
          <Button
            onClick={() => {
              modals.edit({ path, title: itemTitle(item.kind), note: `${engine.name} only` });
            }}
          >
            Open
          </Button>
        )}
        {path !== null && item.folder && openPath !== null && (
          <Button
            onClick={() => {
              openPath(path);
            }}
          >
            Open folder
          </Button>
        )}
      </div>
      {connectors && open && (
        <div className="dkc-indent">
          <ConnectorsList />
        </div>
      )}
    </>
  );
}

/** Plugins: the installed ones fold open; Browse and Marketplaces fold open under them. */
function PluginsFrame({
  engine,
  item,
  count,
  rows,
  browse,
  markets,
}: {
  engine: EngineSection;
  item: EngineItem;
  count: number;
  rows: ReactNode;
  browse: ReactNode;
  markets: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [marketsOpen, setMarketsOpen] = useState(false);
  return (
    <>
      <div className="dkc-item">
        <FoldTitle
          open={open}
          onToggle={() => {
            setOpen(!open);
          }}
          engine={engine}
          item={item}
        />
        <span className="dkc-fill" />
        <Button
          kind={browsing ? "primary" : "soft"}
          aria-pressed={browsing}
          onClick={() => {
            setBrowsing(!browsing);
          }}
        >
          Browse
        </Button>
        <Button
          kind={marketsOpen ? "primary" : "soft"}
          aria-pressed={marketsOpen}
          onClick={() => {
            setMarketsOpen(!marketsOpen);
          }}
        >
          {count > 0 ? `Marketplaces ${String(count)}` : "Marketplaces"}
        </Button>
      </div>
      {open && rows}
      {browsing && <div className="dkc-indent">{browse}</div>}
      {marketsOpen && <div className="dkc-indent">{markets}</div>}
    </>
  );
}

function ClaudePluginsItem({ engine, item }: { engine: EngineSection; item: EngineItem }) {
  const { state, actions } = useStore();
  useEffect(() => {
    if (state.settings.marketplaces === null) void actions.loadExtensions();
  }, [actions, state.settings.marketplaces]);
  return (
    <PluginsFrame
      engine={engine}
      item={item}
      count={state.settings.marketplaces?.length ?? 0}
      rows={<ClaudePluginRows />}
      browse={<BrowseSection />}
      markets={<MarketplacesSection />}
    />
  );
}

function CodexPluginsItem({ engine, item }: { engine: EngineSection; item: EngineItem }) {
  const codex = useCodexPlugins();
  return (
    <PluginsFrame
      engine={engine}
      item={item}
      count={codex.marketplaces.length}
      rows={<CodexPluginRows codex={codex} />}
      browse={<CodexBrowse codex={codex} />}
      markets={<CodexMarketplaces codex={codex} />}
    />
  );
}
