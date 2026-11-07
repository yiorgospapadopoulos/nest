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
    async (started: AccountSignIn) => {
      if (started.auth_url !== null) await bridge.openExternal(started.auth_url);
    },
    [bridge],
  );
  return {
    add: (provider: AccountProvider) => {
      change(`Could not add a ${engineTitle(provider)} account`, async () => {
        await openPage(await api.addAccount(provider));
      });
    },
    signIn: (id: string) => {
      change("Could not start signing in", async () => {
        await openPage(await api.signInAccount(id));
      });
    },
  };
}
