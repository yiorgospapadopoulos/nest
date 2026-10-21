import { ApiError, type Api } from "../api/client.ts";
import { str } from "../api/payloads.ts";
import type {
  AvailablePlugin,
  CodexMarketplace,
  CodexPlugins,
  ConfigurationPage,
  CopyPreview,
  CopyResult,
  EngineId,
  FileText,
  JsonObject,
  McpServer,
  ProjectConfiguration,
  SharedItem,
  Device,
  ListedDevice,
  InstalledPlugin,
  Marketplace,
  PluginDetails,
  PairingCode,
  RepoConfig,
  RepoPatch,
  StorageUsage,
  StoredAttachment,
} from "../api/types.ts";
import type { Action, SettingsState, Toast } from "./state.ts";

// How many of the largest attachments Clean up lists.
export const LARGE_ATTACHMENTS = 20;

interface Tools {
  dispatch: (action: Action) => void;
  attempt: <T>(call: () => Promise<T>) => Promise<T | null>;
  quietly: <T>(call: () => Promise<T>) => Promise<T | null>;
  toast: (text: string, tone?: Toast["tone"]) => void;
}

/** What saving a setup file did: its new version, or the version found on disk instead. */
export type FileSave = { version: string } | { conflict: string | null };

// The settings sections saved whole with PUT, by their key in the state.
type Section = "usage" | "stuck" | "storage" | "pixies";
type Saved<K extends Section> = NonNullable<SettingsState[K]>;

/** What the Settings pages do (B81): load and save the daemon's sections and accounts. */
export function settingsActions(api: Api, { dispatch, attempt, quietly, toast }: Tools) {
  const set = (change: Partial<SettingsState>) => {
    dispatch({ type: "settings", change });
  };

  // Whether Configuration loaded Claude's plugins, which a change elsewhere then loads again.
  let extensionsShown = false;

  async function loadExtensions(): Promise<void> {
    extensionsShown = true;
    const found = await attempt(() => Promise.all([api.plugins(), api.marketplaces()]));
    if (found === null) return;
    const [plugins, marketplaces] = found;
    set({ plugins, marketplaces });
  }

  /** Runs a write, then loads the lists again; `done` is the toast on success. */
  async function extensionWrite(call: () => Promise<unknown>, done: string): Promise<boolean> {
    if ((await attempt(() => call().then(() => true))) === null) return false;
    toast(done);
    await loadExtensions();
    return true;
  }

  // Whether Configuration loaded its page, and the projects whose part was loaded: a
  // change on disk loads those again.
  let configurationShown = false;
  const projectsShown = new Set<string>();

  async function loadConfiguration(): Promise<boolean> {
    configurationShown = true;
    const configuration = await attempt(() => api.configuration());
    if (configuration === null) return false;
    set({ configuration });
    return true;
  }

  /** Runs a write that answers with the page, and shows that page. */
  async function pageWrite(call: () => Promise<ConfigurationPage>): Promise<boolean> {
    const configuration = await attempt(call);
    if (configuration === null) return false;
    set({ configuration });
    return true;
  }

  async function loadProjectConfiguration(repo: string): Promise<boolean> {
    projectsShown.add(repo);
    return projectWrite(repo, () => api.projectConfiguration(repo));
  }

  /** Runs a call that answers with the project's part, and shows it. */
  async function projectWrite(
    repo: string,
    call: () => Promise<ProjectConfiguration>,
  ): Promise<boolean> {
    const configuration = await attempt(call);
    if (configuration === null) return false;
    dispatch({ type: "projectConfiguration", repo, configuration });
    return true;
  }

  const SAVE: { [K in Section]: (value: Saved<K>) => Promise<Saved<K>> } = {
    usage: (value) => api.saveUsageSettings(value),
    stuck: (value) => api.saveStuckSettings(value),
    storage: (value) => api.saveStorageSettings(value),
    pixies: (value) => api.savePixieDefaults(value),
  };

  return {
    /**
     * Every section and account the Settings pages show. Quiet: a section the Mac cannot
     * give (an older daemon) only leaves its rows loading.
     */
    async loadSettings(): Promise<void> {
      const [usage, stuck, storage, pixies, github, claude, codex] = await Promise.all([
        quietly(() => api.usageSettings()),
        quietly(() => api.stuckSettings()),
        quietly(() => api.storageSettings()),
        quietly(() => api.pixieDefaults()),
        quietly(() => api.github()),
        quietly(() => api.claudeAccount()),
        quietly(() => api.codexAccount()),
      ]);
      const found = { usage, stuck, storage, pixies, github, claude, codex };
      const loaded: Partial<SettingsState> = Object.fromEntries(
        Object.entries(found).filter(([, value]) => value !== null),
      );
      set(loaded);
    },

    /** Shows the change at once and puts `previous` back if the Mac refuses it. */
    async saveSection<K extends Section>(
      key: K,
      next: Saved<K>,
      previous: Saved<K>,
    ): Promise<void> {
      set({ [key]: next });
      const saved = await attempt(() => SAVE[key](next));
      set({ [key]: saved ?? previous });
    },

    async checkGithub(): Promise<void> {
      const github = await attempt(() => api.checkGithub());
      if (github !== null) set({ github });
    },

    /** The Mac opens the browser; `account.claude` reports how it went. */
    async claudeLogin(): Promise<void> {
      if ((await attempt(() => api.claudeLogin().then(() => true))) !== null) {
        toast("Finish signing in in the browser on your Mac", "info");
      }
    },

    async claudeLogout(): Promise<void> {
      const claude = await attempt(() => api.claudeLogout());
      if (claude !== null) set({ claude });
    },

    /** Codex's sign out (B94); signing in happens on the Mac only. */
    async codexLogout(): Promise<void> {
      const codex = await attempt(() => api.codexLogout());
      if (codex !== null) set({ codex });
    },

    /** Runs Anthropic's installer on the Mac; `claude_code.install` events follow. */
    async installClaudeCode(): Promise<void> {
      if ((await attempt(() => api.installClaudeCode().then(() => true))) !== null) {
        set({ install: { state: "running", message: null } });
      }
    },

    storage(): Promise<StorageUsage | null> {
      return attempt(() => api.storage());
    },

    largeAttachments(): Promise<StoredAttachment[] | null> {
      return attempt(() => api.largeAttachments(LARGE_ATTACHMENTS));
    },

    async deleteAttachment(attachment: StoredAttachment): Promise<boolean> {
      const done = await attempt(() => api.deleteAttachment(attachment.id).then(() => true));
      if (done === null) return false;
      toast(`Deleted ${attachment.name}`, "info");
      return true;
    },

    async rebuildSearch(): Promise<void> {
      if ((await attempt(() => api.rebuildSearch().then(() => true))) !== null) {
        toast("Rebuilding the search index");
      }
    },

    /** The daemon's version; quiet, as the page works without it. */
    async version(): Promise<string | null> {
      const health = await quietly(() => api.health());
      return health?.version ?? null;
    },

    devices(): Promise<ListedDevice[] | null> {
      return attempt(() => api.devices());
    },

    async revokeDevice(device: Device): Promise<boolean> {
      const done = await attempt(() => api.revokeDevice(device.id).then(() => true));
      if (done === null) return false;
      toast(`Revoked ${device.name}`, "info");
      return true;
    },

    pairingCode(): Promise<PairingCode | null> {
      return attempt(() => api.pairingCode());
    },

    branches(repo: string): Promise<string[] | null> {
      return attempt(() => api.branches(repo).then((found) => found.branches));
    },

    /** Saves project settings; the Mac's answer replaces the project. */
    async updateRepo(repo: RepoConfig, patch: RepoPatch): Promise<boolean> {
      const updated = await attempt(() => api.updateRepo(repo.name, patch));
      if (updated === null) return false;
      dispatch({ type: "repo", repo: updated });
      return true;
    },

    /** How many artifacts the project has; null when the Mac cannot say. */
    async artifactCount(repo: string): Promise<number | null> {
      const found = await quietly(() => api.artifacts({ repo }));
      return found?.length ?? null;
    },

    loadExtensions,

    /** `extensions.updated`: another device or the Mac changed them. */
    async extensionsChanged(): Promise<void> {
      if (extensionsShown) await loadExtensions();
    },

    /** Shows the switch at once and puts the list back if the Mac refuses. */
    async setPluginEnabled(
      plugins: InstalledPlugin[],
      plugin: InstalledPlugin,
      enabled: boolean,
    ): Promise<void> {
      set({ plugins: plugins.map((p) => (p.id === plugin.id ? { ...p, enabled } : p)) });
      const done = await attempt(() => api.setPluginEnabled(plugin.id, enabled).then(() => true));
      if (done === null) set({ plugins });
    },

    uninstallPlugin(plugin: InstalledPlugin): Promise<boolean> {
      return extensionWrite(() => api.uninstallPlugin(plugin.id), `Removed ${plugin.name}`);
    },

    installPlugin(plugin: { id: string; name: string }): Promise<boolean> {
      return extensionWrite(() => api.installPlugin(plugin.id), `Installed ${plugin.name}`);
    },

    addMarketplace(source: string): Promise<boolean> {
      return extensionWrite(() => api.addMarketplace(source), "Marketplace added");
    },

    removeMarketplace(marketplace: Marketplace): Promise<boolean> {
      return extensionWrite(
        () => api.removeMarketplace(marketplace.name),
        `Removed ${marketplace.name}`,
      );
    },

    availablePlugins(): Promise<AvailablePlugin[] | null> {
      return attempt(() => api.availablePlugins());
    },

    pluginDetails(id: string): Promise<PluginDetails | null> {
      return attempt(() => api.pluginDetails(id));
    },

    // Settings > Configuration (B97, B102 item 31).

    loadConfiguration,

    /** `configuration.changed`: the engines' files changed on disk; what is shown loads again. */
    async configurationChanged(payload: JsonObject): Promise<void> {
      const repo = str(payload.repo);
      if (payload.scope === "repo") {
        if (repo !== null && projectsShown.has(repo)) await loadProjectConfiguration(repo);
      } else if (configurationShown) {
        await loadConfiguration();
      }
    },

    setUsesShared(engine: EngineId, item: SharedItem, on: boolean): Promise<boolean> {
      return pageWrite(() => api.setUsesShared(engine, item, on));
    },

    createSkill(name: string, description: string): Promise<boolean> {
      return pageWrite(() => api.createSkill(name, description));
    },

    deleteSkill(name: string): Promise<boolean> {
      return pageWrite(() => api.deleteSkill(name));
    },

    makeSkillShared(name: string): Promise<boolean> {
      return pageWrite(() => api.makeSkillShared(name));
    },

    setCodexSkill(name: string, enabled: boolean): Promise<boolean> {
      return pageWrite(() => api.setCodexSkill(name, enabled));
    },

    /** The server in Claude's shape, for its edit form. */
    mcpServer(name: string): Promise<McpServer | null> {
      return attempt(() => api.mcpServer(name));
    },

    putMcpServer(name: string, server: McpServer): Promise<boolean> {
      return pageWrite(() => api.putMcpServer(name, server));
    },

    deleteMcpServer(name: string): Promise<boolean> {
      return pageWrite(() => api.deleteMcpServer(name));
    },

    copyPreview(engine: EngineId): Promise<CopyPreview | null> {
      return attempt(() => api.copyPreview(engine));
    },

    /** Copies the engine's setup to Shared; the done line and its Undo come back. */
    async copyToShared(
      engine: EngineId,
      instructions: boolean,
    ): Promise<Omit<CopyResult, "page"> | null> {
      const done = await attempt(() => api.copyToShared(engine, instructions));
      if (done === null) return null;
      set({ configuration: done.page });
      return { summary: done.summary, undo_id: done.undo_id };
    },

    undoCopy(undoId: string): Promise<boolean> {
      return pageWrite(() => api.undoCopy(undoId));
    },

    /** A setup file's text for its editor; a missing file reads as empty, version null. */
    readConfigFile(path: string): Promise<FileText | null> {
      return attempt(() => api.configurationFile(path));
    },

    /**
     * Saves a setup file read at `expected`. When it changed on disk since, the version
     * there comes back instead (null once deleted), for Reload or Keep mine; other refusals
     * are reported and give null.
     */
    async writeConfigFile(
      path: string,
      text: string,
      expected: string | null,
    ): Promise<FileSave | null> {
      return attempt(async (): Promise<FileSave> => {
        try {
          return await api.writeConfigurationFile(path, text, expected);
        } catch (error) {
          if (!(error instanceof ApiError && error.status === 409)) throw error;
          const current = error.data.current_version;
          return { conflict: typeof current === "string" ? current : null };
        }
      });
    },

    codexPlugins(query: string): Promise<CodexPlugins | null> {
      return attempt(() => api.codexPlugins(query));
    },

    installCodexPlugin(id: string): Promise<CodexPlugins | null> {
      return attempt(() => api.installCodexPlugin(id));
    },

    uninstallCodexPlugin(id: string): Promise<CodexPlugins | null> {
      return attempt(() => api.uninstallCodexPlugin(id));
    },

    codexMarketplaces(): Promise<CodexMarketplace[] | null> {
      return attempt(() => api.codexMarketplaces());
    },

    addCodexMarketplace(source: string): Promise<CodexMarketplace[] | null> {
      return attempt(() => api.addCodexMarketplace(source));
    },

    removeCodexMarketplace(name: string): Promise<CodexMarketplace[] | null> {
      return attempt(() => api.removeCodexMarketplace(name));
    },

    /** Settings > Project: the repo's own instructions, skills and MCP servers. */
    loadProjectConfiguration,

    putProjectMcpServer(repo: string, name: string, server: McpServer): Promise<boolean> {
      return projectWrite(repo, () => api.putProjectMcpServer(repo, name, server));
    },

    deleteProjectMcpServer(repo: string, name: string): Promise<boolean> {
      return projectWrite(repo, () => api.deleteProjectMcpServer(repo, name));
    },

    createProjectSkill(repo: string, name: string, description: string): Promise<boolean> {
      return projectWrite(repo, () => api.createProjectSkill(repo, name, description));
    },
  };
}
