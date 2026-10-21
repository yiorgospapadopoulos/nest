import { useEffect, useId, useState, type ReactNode } from "react";
import type {
  ConfigurationPage,
  CopyPreview,
  EngineItem,
  EngineSection,
  SkillItem,
} from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { Confirm } from "../pixies/Confirm.tsx";
import { ClaudeBrowse, ClaudeMarketplaces, ClaudePluginRows } from "./ClaudePlugins.tsx";
import { CodexPluginsPart } from "./CodexPlugins.tsx";
import { ConfigEditor, type EditTarget } from "./ConfigEditor.tsx";
import { ServerFormSheet, SkillFormSheet } from "./ConfigForms.tsx";
import {
  copyTitle,
  engineLine,
  FILES_ON_MAC,
  fileName,
  fixedCaption,
  FOOTER,
  INTRO,
  itemDetail,
  itemTitle,
  missingNote,
  NEW_SERVER,
  offersCopy,
  rulesElsewhere,
  serverEngines,
  serverForm,
  SHARED_ITEMS,
  shortPath,
  showsCodexSwitch,
  shownSkills,
  skillDetail,
  skillsToggle,
  skillTag,
  standaloneLine,
  type ServerForm,
} from "./configText.ts";
import { ConnectorGroups } from "./ConnectorsCard.tsx";
import { CopySheet, type CopyDone } from "./CopySheet.tsx";
import { Loading, Row, Section, SwitchRow } from "./rows.tsx";

/** A form over the page: a server to add or edit, or a new skill. */
type Form = { server: ServerForm; isNew: boolean } | { skill: true };

/** What the page's parts ask the page to open. */
interface Open {
  edit: (target: EditTarget) => void;
  form: (form: Form) => void;
}

/**
 * Settings > Configuration (B97, B102 item 31): what the agents read. Shared instructions,
 * skills and MCP servers on top, then a fold-open section per signed-in engine, one open at
 * a time. The engines' own files are the only source of truth; the page follows them live.
 */
export function ConfigurationView() {
  const { state, actions } = useStore();
  const page = state.settings.configuration;
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [copy, setCopy] = useState<{ engine: EngineSection; preview: CopyPreview } | null>(null);
  const [done, setDone] = useState<CopyDone | null>(null);
  // The engine open; undefined until the user picks one, while the first opens.
  const [chosen, setChosen] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    void actions.loadConfiguration();
  }, [actions]);

  const open: Open = { edit: setEditing, form: setForm };
  const openEngine =
    chosen === undefined
      ? (page?.engines[0]?.id ?? null)
      : page?.engines.some((e) => e.id === chosen) === true
        ? chosen
        : null;
  const startCopy = async (engine: EngineSection) => {
    const preview = await actions.copyPreview(engine.id);
    if (preview === null) return;
    setDone(null);
    setCopy({ engine, preview });
  };

  return (
    <div className="cfg">
      <p className="cfg-intro">{INTRO}</p>
      {page === null ? (
        <Loading />
      ) : (
        <>
          <Shared page={page} open={open} />
          <h2 className="pg-h">Engines</h2>
          {page.engines.map((engine) => (
            <Engine
              key={engine.id}
              engine={engine}
              open={openEngine === engine.id}
              done={done?.engine === engine.id ? done : null}
              onToggle={() => {
                setChosen(openEngine === engine.id ? null : engine.id);
              }}
              onCopy={() => void startCopy(engine)}
              onUndone={() => {
                setDone(null);
              }}
            />
          ))}
        </>
      )}
      <p className="note cfg-foot">{FOOTER}</p>
      {editing !== null && (
        <ConfigEditor
          target={editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
      {form !== null && page !== null && (
        <FormSheet
          form={form}
          folder={page.shared.skills.folder}
          open={open}
          onClose={() => {
            setForm(null);
          }}
        />
      )}
      {copy !== null && (
        <CopySheet
          engine={copy.engine.id}
          name={copy.engine.name}
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

function FormSheet({
  form,
  folder,
  open,
  onClose,
}: {
  form: Form;
  folder: string;
  open: Open;
  onClose: () => void;
}) {
  if ("skill" in form) {
    return (
      <SkillFormSheet
        repo={null}
        onClose={onClose}
        onCreated={(name) => {
          onClose();
          open.edit({ path: `${folder}/${name}/SKILL.md`, title: name, note: "shared skill" });
        }}
      />
    );
  }
  return <ServerFormSheet initial={form.server} isNew={form.isNew} repo={null} onClose={onClose} />;
}

/** A row that folds open the rows under it. */
export function FoldRow({
  open,
  onToggle,
  label,
  hint,
  tools,
}: {
  open: boolean;
  onToggle: () => void;
  label: ReactNode;
  hint?: ReactNode;
  tools?: ReactNode;
}) {
  return (
    <div className="srow cfg-foldrow">
      <button className="cfg-fold" aria-expanded={open} onClick={onToggle}>
        <Icon name="chev" className="cv" />
        <span className="slab">
          <span>{label}</span>
          {hint !== undefined && <span className="hint">{hint}</span>}
        </span>
      </button>
      {tools !== undefined && <div className="sctl">{tools}</div>}
    </div>
  );
}

function Shared({ page, open }: { page: ConfigurationPage; open: Open }) {
  const { instructions, skills, mcp_servers: servers } = page.shared;
  const holder = rulesElsewhere(page);
  const codexIn = page.engines.some((e) => e.id === "codex");
  const [skillsOpen, setSkillsOpen] = useState(false);
  const [serversOpen, setServersOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const toggle = skillsToggle(skills.items.length, showAll);
  return (
    <Section title="Shared">
      <Row
        label={
          <>
            <span>
              Instructions <span className="mono cfg-file">{fileName(instructions.path)}</span>
            </span>
            <span className="hint">
              {holder === null
                ? "Read by Codex as it is; Claude's CLAUDE.md imports it. "
                : `Empty. Your rules are in ${holder.name}'s CLAUDE.md; copy them here to share them with every engine. `}
              <span className="mono">{shortPath(instructions.path)}</span>
            </span>
          </>
        }
      >
        <button
          className="b"
          aria-label="Edit instructions"
          onClick={() => {
            open.edit({
              path: instructions.path,
              title: "Instructions",
              note: "used by Claude and Codex",
            });
          }}
        >
          Edit
        </button>
      </Row>
      <FoldRow
        open={skillsOpen}
        onToggle={() => {
          setSkillsOpen(!skillsOpen);
        }}
        label={
          <>
            Skills <span className="cfg-n">{skills.items.length}</span>
          </>
        }
        hint={
          <>
            One folder for every engine. <span className="mono">{shortPath(skills.folder)}</span>
          </>
        }
      />
      {skillsOpen && (
        <>
          <ul className="cfg-list" aria-label="Shared skills">
            {shownSkills(skills.items, showAll).map((skill) => (
              <SkillRow key={skill.path} skill={skill} codexIn={codexIn} open={open} />
            ))}
          </ul>
          <div className="srow sub cfg-tools">
            {toggle !== null && (
              <button
                className="lnk"
                onClick={() => {
                  setShowAll(!showAll);
                }}
              >
                {toggle}
              </button>
            )}
            <button
              className="b"
              onClick={() => {
                open.form({ skill: true });
              }}
            >
              New skill
            </button>
          </div>
        </>
      )}
      <FoldRow
        open={serversOpen}
        onToggle={() => {
          setServersOpen(!serversOpen);
        }}
        label={
          <>
            MCP servers <span className="cfg-n">{servers.length}</span>
          </>
        }
        hint="Set up once; Nest writes each into every engine's own config."
      />
      {serversOpen && (
        <>
          <ul className="cfg-list" aria-label="Shared MCP servers">
            {servers.map((server) => (
              <li key={server.name} className="srow item sub">
                <span className="slab">
                  {server.name}
                  <span className="hint mono">{server.summary}</span>
                  {server.convertible ? (
                    <span className="hint">{serverEngines(server).join(" · ")}</span>
                  ) : (
                    <span className="hint">
                      Claude only{server.reason === null ? "" : `: ${server.reason}`}
                    </span>
                  )}
                </span>
                <EditServer name={server.name} open={open} />
              </li>
            ))}
          </ul>
          <div className="srow sub cfg-tools">
            <button
              className="b"
              onClick={() => {
                open.form({ server: NEW_SERVER, isNew: true });
              }}
            >
              Add server
            </button>
          </div>
        </>
      )}
    </Section>
  );
}

function EditServer({ name, open }: { name: string; open: Open }) {
  const { actions } = useStore();
  return (
    <button
      className="b"
      aria-label={`Edit ${name}`}
      onClick={() =>
        void actions.mcpServer(name).then((server) => {
          if (server !== null) open.form({ server: serverForm(name, server), isNew: false });
        })
      }
    >
      Edit
    </button>
  );
}

function SkillRow({ skill, codexIn, open }: { skill: SkillItem; codexIn: boolean; open: Open }) {
  const { actions } = useStore();
  const [removing, setRemoving] = useState(false);
  const id = useId();
  const detail = skillDetail(skill);
  return (
    <li className="srow item sub">
      <span className="slab" id={id}>
        {skill.name}
        {detail !== "" && <span className="hint">{detail}</span>}
        <span className="hint cfg-tags">
          <span>{skillTag(skill)}</span>
          {codexIn && skill.codex_error !== null && (
            <span className="cfg-warn">not loaded by Codex</span>
          )}
          {skill.read_only && <span>read only</span>}
        </span>
      </span>
      <div className="sctl">
        {codexIn && showsCodexSwitch(skill) && (
          <button
            className="sw"
            role="switch"
            aria-checked={skill.codex_enabled === true}
            aria-label={`Load ${skill.name} in Codex`}
            onClick={() => void actions.setCodexSkill(skill.name, skill.codex_enabled !== true)}
          />
        )}
        {skill.source === "engine_only" && (
          <button
            className="b"
            aria-label={`Make ${skill.name} shared`}
            onClick={() => void actions.makeSkillShared(skill.name)}
          >
            Make shared
          </button>
        )}
        {skill.source !== "engine_only" && !skill.read_only && (
          <button
            className="b"
            aria-label={`Edit ${skill.name}`}
            onClick={() => {
              open.edit({ path: skill.path, title: skill.name, note: "skill" });
            }}
          >
            Edit
          </button>
        )}
        {skill.source === "yours" && (
          <button
            className="b"
            aria-label={`Remove ${skill.name}`}
            onClick={() => {
              setRemoving(true);
            }}
          >
            Remove
          </button>
        )}
      </div>
      {removing && (
        <Confirm
          title={`Remove ${skill.name}?`}
          about="Its folder is removed from the shared skills, for every engine."
          action="Remove"
          onConfirm={() => void actions.deleteSkill(skill.name)}
          onClose={() => {
            setRemoving(false);
          }}
        />
      )}
    </li>
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

function Engine({ engine, open, done, onToggle, onCopy, onUndone }: EngineProps) {
  const { actions } = useStore();
  const note =
    missingNote(engine.missing_from_shared) ??
    (done === null ? null : `Shared matches ${engine.name}`);
  const counted = engine.items.filter((i) => i.kind !== "plugins" && i.kind !== "connectors");
  const captions = SHARED_ITEMS.flatMap(({ item }) =>
    engine.uses_shared[item].fixed ? [fixedCaption(engine.id, item)] : [],
  ).filter((c) => c !== null);
  return (
    <section className="eng" aria-label={engine.name}>
      <button className="eng-h" aria-expanded={open} onClick={onToggle}>
        <Icon name="chev" className="cv" />
        <span className="eng-n">{engine.name}</span>
        {engine.account !== null && <small>{engine.account}</small>}
      </button>
      {open && (
        <>
          {(offersCopy(engine) || note !== null) && (
            <div className="eng-copy">
              {offersCopy(engine) && (
                <button className="b b-pri" onClick={onCopy}>
                  {copyTitle(engine.name)}
                </button>
              )}
              {note !== null && <p className="note">{note}</p>}
            </div>
          )}
          {done !== null && (
            <div className="cfg-done" role="status">
              <Icon name="check" className="cfg-ck" />
              <span>{done.summary}</span>
              <button
                className="b"
                onClick={() =>
                  void actions.undoCopy(done.undoId).then((undone) => {
                    if (undone) onUndone();
                  })
                }
              >
                Undo
              </button>
            </div>
          )}
          <EngineLine engine={engine} />
          {SHARED_ITEMS.map(({ item, title }) => (
            <SwitchRow
              key={item}
              label={`Uses shared ${title}`}
              on={engine.uses_shared[item].on}
              disabled={engine.uses_shared[item].fixed}
              onToggle={() =>
                void actions.setUsesShared(engine.id, item, !engine.uses_shared[item].on)
              }
            />
          ))}
          {captions.length > 0 && <p className="note cfg-cap">{`${captions.join(". ")}.`}</p>}
          {engine.items.map((item) =>
            item.kind === "plugins" ? (
              <PluginsItem key={item.kind} engine={engine} item={item} />
            ) : item.kind === "connectors" ? (
              <ConnectorsItem key={item.kind} engine={engine} item={item} />
            ) : null,
          )}
          {counted.map((item) => (
            <Row key={item.kind} label={itemTitle(item.kind)}>
              <span className="sval">{itemDetail(item, engine)}</span>
            </Row>
          ))}
          {counted.length > 0 && <p className="note cfg-cap">{FILES_ON_MAC}</p>}
        </>
      )}
    </section>
  );
}

/** The version Nest brings, a CLI found on the Mac, else Install Claude Code. */
function EngineLine({ engine }: { engine: EngineSection }) {
  const { state, actions } = useStore();
  const [asking, setAsking] = useState(false);
  const install = state.settings.install;
  const standalone = standaloneLine(engine);
  const claude = engine.id === "claude";
  return (
    <>
      <Row
        label={
          <>
            <span>Engine</span>
            <span className="hint">{engineLine(engine)}</span>
            <span className="hint mono">{shortPath(engine.config_folder)}</span>
          </>
        }
      >
        {standalone !== null && <span className="sval">{standalone}</span>}
        {standalone === null && claude && install?.state === "running" && (
          <span className="sval">{install.message ?? "Installing"}</span>
        )}
        {standalone === null && claude && install?.state !== "running" && (
          <button
            className="b"
            onClick={() => {
              setAsking(true);
            }}
          >
            Install Claude Code
          </button>
        )}
      </Row>
      {claude && install?.state === "failed" && (
        <p className="srow note cfg-bad" role="alert">
          {`Installing failed: ${install.message ?? "no reason given"}`}
        </p>
      )}
      {asking && (
        <Confirm
          title="Install Claude Code?"
          about="Nest runs Anthropic's installer from claude.ai/install.sh, so claude also works in a terminal."
          action="Install"
          neutral
          onConfirm={() => void actions.installClaudeCode()}
          onClose={() => {
            setAsking(false);
          }}
        />
      )}
    </>
  );
}

/** Plugins: the installed ones fold open; Browse and Marketplaces open sheets. */
function PluginsItem({ engine, item }: { engine: EngineSection; item: EngineItem }) {
  const { state } = useStore();
  const [open, setOpen] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [markets, setMarkets] = useState(false);
  const claude = engine.id === "claude";
  const count = claude ? (state.settings.marketplaces?.length ?? 0) : 0;
  return (
    <>
      <FoldRow
        open={open}
        onToggle={() => {
          setOpen(!open);
        }}
        label={itemTitle("plugins")}
        hint={itemDetail(item, engine)}
        tools={
          <>
            <button
              className="b"
              onClick={() => {
                setBrowsing(true);
              }}
            >
              Browse
            </button>
            <button
              className="b"
              onClick={() => {
                setMarkets(true);
              }}
            >
              {count > 0 ? `Marketplaces ${String(count)}` : "Marketplaces"}
            </button>
          </>
        }
      />
      {claude ? (
        <>
          {open && <ClaudePluginRows />}
          {browsing && (
            <ClaudeBrowse
              onClose={() => {
                setBrowsing(false);
              }}
            />
          )}
          {markets && (
            <ClaudeMarketplaces
              onClose={() => {
                setMarkets(false);
              }}
            />
          )}
        </>
      ) : (
        <CodexPluginsPart
          open={open}
          browsing={browsing}
          markets={markets}
          onCloseBrowse={() => {
            setBrowsing(false);
          }}
          onCloseMarkets={() => {
            setMarkets(false);
          }}
        />
      )}
    </>
  );
}

/** claude.ai's connectors, read only here: they are set up on claude.ai. */
function ConnectorsItem({ engine, item }: { engine: EngineSection; item: EngineItem }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <FoldRow
        open={open}
        onToggle={() => {
          setOpen(!open);
        }}
        label={itemTitle("connectors")}
        hint={itemDetail(item, engine)}
        tools={<span className="sval">Claude only</span>}
      />
      {open && (
        <div className="cfg-conn">
          <ConnectorGroups opened={false} />
        </div>
      )}
    </>
  );
}
