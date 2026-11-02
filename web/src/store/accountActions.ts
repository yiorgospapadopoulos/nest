import { ApiError, type Api } from "../api/client.ts";
import { ACCOUNTS_CHANGED } from "../api/events.ts";
import { accountsOf } from "../api/payloads.ts";
import type {
  BankedResets,
  CheckResult,
  EngineAccount,
  FoundModel,
  FoundModels,
  LocalEngine,
  NestEvent,
  ResetOutcome,
} from "../api/types.ts";
import { loadUsageMeter, saveUsageMeter } from "./devicePrefs.ts";
import type { Action, SettingsState, Toast } from "./state.ts";
import { withShown, type MeterAccount, type UsageMeterChoice } from "./usageMeter.ts";

interface Tools {
  dispatch: (action: Action) => void;
  attempt: <T>(call: () => Promise<T>) => Promise<T | null>;
  quietly: <T>(call: () => Promise<T>) => Promise<T | null>;
  toast: (text: string, tone?: Toast["tone"]) => void;
  // localActions' own: the model list the menus and Accounts share.
  loadLocalModels: () => Promise<void>;
}

// What using a banked reset did, as the Mac's AccountText.useOutcome says it.
const OUTCOMES: Record<ResetOutcome, string> = {
  reset: "Limits reset",
  nothing_to_reset: "Nothing to reset yet",
  no_credit: "No banked resets left",
  already_redeemed: "That reset was already used",
};

/**
 * Settings > Accounts' engine accounts (B98, D124) and the Usage page's choice of them, as
 * the Mac's AccountsStore: the list loads with `GET /api/accounts` and follows
 * `accounts.changed`; adding and signing in stay on the Mac.
 */
export function accountActions(
  api: Api,
  storage: () => Storage,
  { dispatch, attempt, quietly, toast, loadLocalModels }: Tools,
) {
  // What the state holds, so a change can be made against it and put back.
  let accounts: EngineAccount[] | null = null;
  let banked: Record<string, BankedResets> = {};
  let meter = loadUsageMeter(storage);

  const set = (change: Partial<SettingsState>) => {
    dispatch({ type: "settings", change });
  };
  const put = (next: EngineAccount[]) => {
    accounts = next;
    set({ accounts: next });
  };
  // One account as the daemon answered for it.
  const putOne = (changed: EngineAccount) => {
    if (accounts !== null) put(accounts.map((a) => (a.id === changed.id ? changed : a)));
  };
  const find = (id: string) => accounts?.find((a) => a.id === id) ?? null;
  const setMeter = (next: UsageMeterChoice) => {
    meter = next;
    saveUsageMeter(storage, next);
    set({ usageMeter: next });
  };

  async function loadBanked(id: string): Promise<void> {
    const found = await quietly(() => api.bankedResets(id));
    if (found === null) return;
    banked = { ...banked, [id]: found };
    set({ bankedResets: banked });
  }

  return {
    async loadAccounts(): Promise<void> {
      const list = await quietly(() => api.accounts());
      if (list !== null) put(list.accounts);
    },

    /** New usage windows for every signed-in account; too soon after the last, a note. */
    async refreshAccounts(): Promise<void> {
      const list = await attempt(async () => {
        try {
          return await api.refreshAccounts();
        } catch (error) {
          if (!(error instanceof ApiError && error.status === 429)) throw error;
          toast("Usage was refreshed moments ago", "info");
          return null;
        }
      });
      if (list !== null) put(list.accounts);
    },

    /**
     * Moves the engine's check at once, and back if the Mac refuses; a signed-out account
     * cannot take it.
     */
    async activateAccount(id: string): Promise<void> {
      const account = find(id);
      if (accounts === null || account === null || account.active) return;
      if (account.signed_in !== true) return;
      const previous = accounts;
      put(
        previous.map((a) => (a.provider === account.provider ? { ...a, active: a.id === id } : a)),
      );
      const list = await attempt(() => api.activateAccount(id));
      put(list?.accounts ?? previous);
    },

    /** Trimmed; empty clears the name. An unchanged name is not sent. */
    async renameAccount(id: string, text: string): Promise<void> {
      const account = find(id);
      if (account === null) return;
      const trimmed = text.trim();
      const name = trimmed === "" ? null : trimmed;
      if (name === account.name || (account.name === null && name === account.title)) return;
      const changed = await attempt(() => api.renameAccount(id, name));
      if (changed !== null) putOne(changed);
    },

    async signOutAccount(id: string): Promise<void> {
      const changed = await attempt(() => api.signOutAccount(id));
      if (changed !== null) putOne(changed);
    },

    async removeAccount(id: string): Promise<void> {
      const list = await attempt(() => api.removeAccount(id));
      if (list !== null) put(list.accounts);
    },

    /** Each signed-in account's banked resets of the engine; one that cannot say keeps its last. */
    async loadBankedResets(provider: string): Promise<void> {
      const signedIn = (accounts ?? []).filter(
        (a) => a.provider === provider && a.signed_in === true,
      );
      await Promise.all(signedIn.map((a) => loadBanked(a.id)));
    },

    /** Spends one banked reset on the account's limits, says what it did, reads them again. */
    async useBankedReset(id: string, creditId: string): Promise<void> {
      const used = await attempt(() => api.useBankedReset(id, creditId));
      if (used === null) return;
      put(used.accounts);
      toast(OUTCOMES[used.outcome], used.outcome === "reset" ? "ok" : "info");
      await loadBanked(id);
    },

    /** Checks or unchecks an account in "Top bar shows", on this device only. */
    setUsageMeterShown(id: string, shown: boolean, entries: MeterAccount[]): void {
      setMeter(withShown(meter, id, shown, entries));
    },

    /** The accounts' ids in the order the user put them. */
    orderUsageMeter(ids: string[]): void {
      setMeter({ ...meter, order: ids });
    },

    // Settings > Accounts' local models (B106, D129); Find and Start act on the Mac.

    async removeLocalModel(id: string): Promise<void> {
      const done = await attempt(() => api.removeLocalModel(id).then(() => true));
      if (done !== null) await loadLocalModels();
    },

    async setLocalEngine(engine: LocalEngine): Promise<void> {
      const done = await attempt(() => api.setLocalEngine(engine).then(() => true));
      if (done !== null) await loadLocalModels();
    },

    /** The servers running on the Mac's usual ports and the models on its disk. */
    findLocalModels(): Promise<FoundModels | null> {
      return attempt(() => api.findLocalModels());
    },

    checkLocalServer(address: string, key: string | null): Promise<CheckResult | null> {
      return attempt(() => api.checkLocalServer(address, key));
    },

    /**
     * Adds each server's chosen models, servers in the order chosen; true once all were
     * added. The key goes only with an address the user entered.
     */
    async addLocalModels(models: FoundModel[], key: string | null): Promise<boolean> {
      const addresses = [...new Set(models.map((m) => m.address))];
      for (const address of addresses) {
        const names = models.filter((m) => m.address === address).map((m) => m.model);
        if ((await attempt(() => api.addLocalModels(address, key, names))) === null) {
          await loadLocalModels();
          return false;
        }
      }
      await loadLocalModels();
      return true;
    },

    /** Called with every live event: `accounts.changed` carries the whole list. */
    accountEvent(event: NestEvent): void {
      if (event.type !== ACCOUNTS_CHANGED) return;
      const list = accountsOf(event.payload);
      if (list !== null) put(list);
    },
  };
}
