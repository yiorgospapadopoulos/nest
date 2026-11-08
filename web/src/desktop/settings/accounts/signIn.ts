import { useCallback } from "react";
import type { AccountProvider, AccountSignIn } from "../../../api/types.ts";
import { engineTitle } from "../../../store/usageMeter.ts";
import { useApi, useBridge } from "../../context.ts";
import { useSettingsChange } from "../config/util.ts";

/** Settings > Accounts' sign-in, the one path the setup guide uses too. */
export function useSignIn() {
  const api = useApi();
  const bridge = useBridge();
  const change = useSettingsChange();
  const openPage = useCallback(
    async (started: AccountSignIn, opened?: (url: string | null) => void) => {
      if (started.auth_url !== null) await bridge.openExternal(started.auth_url);
      opened?.(started.auth_url);
    },
    [bridge],
  );
  // `opened` hears that the sign-in started, with the page's address when the client opened
  // it; Claude Code opens its own page, so then there is none.
  return {
    add: (provider: AccountProvider, opened?: (url: string | null) => void) => {
      change(`Could not add a ${engineTitle(provider)} account`, async () => {
        await openPage(await api.addAccount(provider), opened);
      });
    },
    signIn: (id: string, opened?: (url: string | null) => void) => {
      change("Could not start signing in", async () => {
        await openPage(await api.signInAccount(id), opened);
      });
    },
  };
}
