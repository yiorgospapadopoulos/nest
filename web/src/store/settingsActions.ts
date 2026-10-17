import type { Api } from "../api/client.ts";
import type {
  AvailablePlugin,
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

// The settings sections saved whole with PUT, by their key in the state.
type Section = "usage" | "stuck" | "storage" | "pixies";
type Saved<K extends Section> = NonNullable<SettingsState[K]>;

/** What the Settings pages do (B81): load and save the daemon's sections and accounts. */
export function settingsActions(api: Api, { dispatch, attempt, quietly, toast }: Tools) {
  const set = (change: Partial<SettingsState>) => {
    dispatch({ type: "settings", change });
  };

  // Whether Extensions loaded its lists, which a change elsewhere then loads again.
  let extensionsShown = false;

  async function loadExtensions(): Promise<void> {
    extensionsShown = true;
    const found = await attempt(() =>
      Promise.all([api.plugins(), api.skills(), api.marketplaces()]),
    );
    if (found === null) return;
    const [plugins, skills, marketplaces] = found;
    set({ plugins, skills, marketplaces });
  }

  /** Runs a write, then loads the lists again; `done` is the toast on success. */
  async function extensionWrite(call: () => Promise<unknown>, done: string): Promise<boolean> {
    if ((await attempt(() => call().then(() => true))) === null) return false;
    toast(done);
    await loadExtensions();
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
      const [usage, stuck, storage, pixies, github, claude, claudeCode] = await Promise.all([
        quietly(() => api.usageSettings()),
        quietly(() => api.stuckSettings()),
        quietly(() => api.storageSettings()),
        quietly(() => api.pixieDefaults()),
        quietly(() => api.github()),
        quietly(() => api.claudeAccount()),
        quietly(() => api.claudeCode()),
      ]);
      const found = { usage, stuck, storage, pixies, github, claude, claudeCode };
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
  };
}
