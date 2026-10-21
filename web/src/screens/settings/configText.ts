import type {
  ConfigItemKind,
  ConfigurationPage,
  CopyPreview,
  EngineItem,
  EngineSection,
  McpServer,
  McpTransport,
  SharedItem,
  SharedServer,
  SkillItem,
} from "../../api/types.ts";

// The words of Settings > Configuration (B97, B102 item 31), as NestKit's ConfigurationText.

export const INTRO =
  "What your agents read: instructions, skills, MCP servers and each engine's own settings. These are the same files Claude Code and Codex use in a terminal, so changes here apply there too.";
export const FOOTER = "Other engines appear here once you sign in to them under Accounts.";
export const EDITOR_FOOTER = "Saved files apply from each chat's next message.";
// The engine's own files that the phone only counts.
export const FILES_ON_MAC = "Edit these as files on the Mac.";
export const PROJECT_INTRO =
  "This project's own instructions, skills and MCP servers. Agents read them on top of the shared ones in Configuration.";

// How many skills show before "Show all N".
export const SKILLS_SHOWN = 4;

// sha256 of zero bytes, the version the daemon gives an empty file.
const EMPTY_FILE = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

export const SHARED_ITEMS: { item: SharedItem; title: string }[] = [
  { item: "instructions", title: "instructions" },
  { item: "skills", title: "skills" },
  { item: "mcp_servers", title: "MCP servers" },
];

/** A path in a home folder with `~` for it; the phone does not know the Mac's home. */
export function shortPath(path: string): string {
  return path.replace(/^\/Users\/[^/]+(?=\/|$)/, "~");
}

export function fileName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

/** "Skills and MCP servers are added ..."; the instructions part only when they are replaced. */
export function copyIntro(preview: CopyPreview): string {
  const intro = "Skills and MCP servers are added to what Shared already has.";
  return preview.instructions === null ? intro : `${intro} Only the instructions file is replaced.`;
}

export function copyTitle(engine: string): string {
  return `Copy ${engine}'s setup to Shared`;
}

export function replaceWarning(engine: string): string {
  return `Your shared instructions will be replaced with ${engine}'s. A copy of the current ones is saved first, so you can undo this.`;
}

/** The skills the list shows: the first few, or all of them once asked. */
export function shownSkills(skills: SkillItem[], showAll: boolean): SkillItem[] {
  return showAll ? skills : skills.slice(0, SKILLS_SHOWN);
}

/** "Show all 12" while some are hidden, "Show fewer" while all show, null when they fit. */
export function skillsToggle(count: number, showAll: boolean): string | null {
  if (count <= SKILLS_SHOWN) return null;
  return showAll ? "Show fewer" : `Show all ${String(count)}`;
}

function engineTitle(id: string): string {
  return id.charAt(0).toUpperCase() + id.slice(1);
}

/** The quiet word beside a skill: where it comes from. */
export function skillTag(skill: SkillItem): string {
  switch (skill.source) {
    case "yours":
      return "yours";
    case "synced":
      return "claude.ai account";
    case "plugin":
      return skill.plugin === null ? "plugin" : `plugin ${skill.plugin}`;
    case "engine_only":
      return `${engineTitle(skill.engine ?? "codex")} only`;
    case "project":
      return "project";
  }
}

/** The line under a skill's name: its description, or where an engine-only one was found. */
export function skillDetail(skill: SkillItem): string {
  if (skill.source === "engine_only") {
    return `Found in ${engineTitle(skill.engine ?? "codex")}'s own skills folder`;
  }
  return skill.description ?? "";
}

/**
 * Whether a skill has its Codex switch: claude.ai account skills, and any Codex does not
 * load, while Codex uses the shared skills.
 */
export function showsCodexSwitch(skill: SkillItem): boolean {
  if (skill.codex_enabled === null) return false;
  return skill.source === "synced" || !skill.codex_enabled;
}

function count(n: number, one: string, many: string): string {
  return `${String(n)} ${n === 1 ? one : many}`;
}

/** "Not in Shared yet: instructions, 2 skills, 1 MCP server"; null when Shared has it all. */
export function missingNote(missing: EngineSection["missing_from_shared"]): string | null {
  const parts = [
    ...(missing.instructions ? ["instructions"] : []),
    ...(missing.skills.length > 0 ? [count(missing.skills.length, "skill", "skills")] : []),
    ...(missing.mcp_servers.length > 0
      ? [count(missing.mcp_servers.length, "MCP server", "MCP servers")]
      : []),
  ];
  return parts.length === 0 ? null : `Not in Shared yet: ${parts.join(", ")}`;
}

/** Whether the engine has something Shared lacks, so its section offers the copy. */
export function offersCopy(engine: EngineSection): boolean {
  return missingNote(engine.missing_from_shared) !== null;
}

/** "Claude Code 2.1.163, bundled with Nest". */
export function engineLine(engine: EngineSection): string {
  const product = engine.id === "claude" ? "Claude Code" : engine.name;
  return engine.bundled_version === null
    ? `${product}, bundled with Nest`
    : `${product} ${engine.bundled_version}, bundled with Nest`;
}

/** "Also on this Mac: ~/bin/claude 2.1.160"; null when none was found. */
export function standaloneLine(engine: EngineSection): string | null {
  const found = engine.standalone;
  if (found === null) return null;
  const version = found.version === null ? "" : ` ${found.version}`;
  return `Also on this Mac: ${shortPath(found.path)}${version}`;
}

/** The caption of a switch that cannot change. */
export function fixedCaption(engine: string, item: SharedItem): string | null {
  if (engine === "claude" && item === "skills") return "Claude's own folder is the shared one";
  if (engine === "codex" && item === "instructions") {
    return "Codex's own AGENTS.md is the shared one";
  }
  return null;
}

const ITEM_TITLES: Record<ConfigItemKind, string> = {
  plugins: "Plugins",
  connectors: "Connectors",
  hooks: "Hooks",
  subagents: "Subagents",
  commands: "Slash commands",
  permissions: "Permission rules",
  settings: "Settings file",
  rules: "Rules",
};

export function itemTitle(kind: ConfigItemKind): string {
  return ITEM_TITLES[kind];
}

/**
 * The grey words after an item's title: plugins say how many are installed (another
 * engine's are its own), connectors where they come from; others their detail, else their
 * count, "none" for zero.
 */
export function itemDetail(item: EngineItem, engine: EngineSection): string | null {
  const n = item.count ?? 0;
  if (item.kind === "plugins") {
    const installed = n === 0 ? "none" : `${String(n)} installed`;
    return engine.id === "claude" ? installed : `${engine.name}'s own · ${installed}`;
  }
  if (item.kind === "connectors") return `claude.ai · ${String(n)}`;
  if (item.detail !== null && item.detail !== "") return item.detail;
  if (item.count === null) return null;
  return n === 0 ? "none" : String(n);
}

const ENGINE_ORDER = ["claude", "codex"];

/** "Claude", "Codex" for a shared server, in a fixed order. */
export function serverEngines(server: SharedServer): string[] {
  return [...server.engines]
    .sort((a, b) => ENGINE_ORDER.indexOf(a) - ENGINE_ORDER.indexOf(b))
    .map(engineTitle);
}

/**
 * The engine still holding its own rules while the shared instructions are empty: Claude,
 * when its CLAUDE.md has rules Shared lacks.
 */
export function rulesElsewhere(page: ConfigurationPage): EngineSection | null {
  const { instructions } = page.shared;
  const empty = !instructions.exists || instructions.version === EMPTY_FILE;
  if (!empty) return null;
  return page.engines.find((e) => e.id === "claude" && e.missing_from_shared.instructions) ?? null;
}

// The copy popup.

export interface CopySection {
  title: string;
  // The bold first words, such as "Add 2", and the names after them.
  lead: string | null;
  names: string | null;
  // Grey lines under it.
  notes: string[];
}

const SHARED_HAS_IT = "Shared has a skill with this name";

/** The first three names, then "and N more". */
export function shortList(names: string[]): string {
  const shown = names.slice(0, 3).join(", ");
  return names.length > 3 ? `${shown} and ${String(names.length - 3)} more` : shown;
}

/** "a", "a and b", "a, b and c". */
function list(names: string[]): string {
  if (names.length < 2) return String(names[0]);
  return `${names.slice(0, -1).join(", ")} and ${String(names.at(-1))}`;
}

/** One line per reason, in the order the reasons first come. */
function sameNameNotes(skills: { name: string; reason: string }[]): string[] {
  const groups = new Map<string, string[]>();
  for (const skill of skills)
    groups.set(skill.reason, [...(groups.get(skill.reason) ?? []), skill.name]);
  return [...groups].map(([reason, names]) => {
    const all = `(${shortList(names)})`;
    const n = String(names.length);
    if (reason === SHARED_HAS_IT) {
      const which = names.length === 1 ? "a shared one" : "shared ones";
      return `${n} with the same name as ${which} ${all}: Shared keeps its own`;
    }
    // "Claude has it from plugin superpowers".
    const from = /^(.*) has it from plugin (.*)$/.exec(reason);
    if (from !== null) {
      return `${n} ${String(from[1])} already has from plugin ${String(from[2])} ${all}: left as they are`;
    }
    return `${n} skipped ${all}: ${reason}`;
  });
}

function section(title: string, add: string[], notes: string[]): CopySection {
  return {
    title,
    lead: add.length === 0 ? "Nothing to add" : `Add ${String(add.length)}`,
    names: add.length === 0 ? null : add.join(", "),
    notes,
  };
}

/** The copy popup's sections after the instructions: skills, MCP servers, what stays. */
export function copySections(preview: CopyPreview, engine: string): CopySection[] {
  const { skills, mcp_servers: servers } = preview;
  const skillNotes = [
    ...(skills.already.length > 0
      ? [`${String(skills.already.length)} already in Shared, left as they are`]
      : []),
    ...sameNameNotes(skills.same_name),
  ];
  const serverNotes = [
    ...(servers.already.length > 0 ? [`${list(servers.already)} already in Shared`] : []),
    ...servers.not_convertible.map((s) => `${s.name} stays with ${engine}: ${s.reason}`),
  ];
  const stays = preview.stays.join(", ");
  return [
    section("Skills", skills.add, skillNotes),
    section("MCP servers", servers.add, serverNotes),
    {
      title: `Stays ${engine} only`,
      lead: null,
      names: null,
      notes: stays === "" ? [] : [stays.charAt(0).toUpperCase() + stays.slice(1)],
    },
  ];
}

/**
 * A new skill's name as the daemon accepts it: lower case letters, digits and dashes,
 * starting with a letter or digit, at most 64 characters.
 */
export function isValidSkillName(name: string): boolean {
  return /^[a-z0-9][a-z0-9-]{0,63}$/.test(name);
}

// The Add server and Edit form: a command with its arguments and environment, or a URL
// with its headers, one entry per line.

export interface ServerForm {
  name: string;
  transport: McpTransport;
  command: string;
  args: string;
  env: string;
  url: string;
  headers: string;
}

export const NEW_SERVER: ServerForm = {
  name: "",
  transport: "stdio",
  command: "",
  args: "",
  env: "",
  url: "",
  headers: "",
};

const pairsText = (pairs: Record<string, string> | undefined, separator: string) =>
  Object.entries(pairs ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => `${key}${separator}${value}`)
    .join("\n");

/** The form for an existing server. */
export function serverForm(name: string, server: McpServer): ServerForm {
  return {
    name,
    transport: server.transport,
    command: server.command ?? "",
    args: (server.args ?? []).join("\n"),
    env: pairsText(server.env, "="),
    url: server.url ?? "",
    headers: pairsText(server.headers, ": "),
  };
}

function lines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/** `KEY=value` or `Name: value` lines; lines without the separator are left out. */
function pairs(text: string, separator: string): Record<string, string> {
  const found: Record<string, string> = {};
  for (const line of lines(text)) {
    const at = line.indexOf(separator);
    const key = line.slice(0, Math.max(at, 0)).trim();
    if (key !== "") found[key] = line.slice(at + 1).trim();
  }
  return found;
}

/** The server the form describes; null while it lacks a name, or a command or URL. */
export function formServer(form: ServerForm): McpServer | null {
  if (form.name.trim() === "") return null;
  if (form.transport === "stdio") {
    const command = form.command.trim();
    if (command === "") return null;
    return { transport: "stdio", command, args: lines(form.args), env: pairs(form.env, "=") };
  }
  const url = form.url.trim();
  if (url === "") return null;
  return { transport: form.transport, url, headers: pairs(form.headers, ":") };
}
