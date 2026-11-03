import { useEffect, useState } from "react";
import type { GithubState } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Button } from "../../ui/controls.tsx";
import { otherEngines } from "../accounts/engineSetup.ts";
import { EngineAccounts } from "../accounts/EngineAccounts.tsx";
import { LocalModelsSection } from "../accounts/LocalModels.tsx";
import { MoreEnginesSection } from "../accounts/MoreEngines.tsx";
import { AccountsHeader, AccountsSymbol } from "../accounts/parts.tsx";
import { StatusLabel } from "../config/parts.tsx";
import { SettingsListRow, SettingsSection } from "../rows.tsx";

/**
 * Settings > Accounts, as the Mac's AccountsPage: each engine's accounts, one in use per
 * engine (B98), every other engine as More engines (B107), the local models (B106), first
 * when the user chose them only, and the `gh` login (B81).
 */
export function AccountsPage() {
  const { state, actions } = useStore();
  const local = state.local.list;
  const localFirst = local?.local_only === true;
  // With local models, signing in to an engine is a choice, not a need.
  const optional = local !== null && (local.local_only || local.models.length > 0);
  const others = otherEngines(state.providers ?? []);
  useEffect(() => {
    void actions.loadAccounts();
  }, [actions]);
  return (
    <div className="dka-page">
      {localFirst && <LocalModelsSection />}
      <EngineAccounts provider="claude" optional={optional} />
      <EngineAccounts provider="codex" optional={optional} />
      {others.length > 0 && <MoreEnginesSection setups={others} />}
      {!localFirst && <LocalModelsSection />}
      <GitHubSection />
    </div>
  );
}

const GITHUB: Record<GithubState, string> = {
  signed_in: "Signed in",
  signed_out: "Signed out",
  unavailable: "gh is not installed",
};

function GitHubSection() {
  const { state, actions } = useStore();
  const github = state.settings.github;
  const [checking, setChecking] = useState(false);
  const signedIn = github?.state === "signed_in";
  return (
    <SettingsSection bare>
      <AccountsHeader title="GitHub" mark={<AccountsSymbol name="pullRequest" />} />
      <div className="dka-rows">
        <SettingsListRow
          title={github?.login ?? "GitHub"}
          leading={
            <span className="dks-badge" aria-hidden="true">
              gh
            </span>
          }
          trailing={
            <>
              {github !== null && (
                <StatusLabel
                  tone={signedIn ? "review" : "waiting"}
                  label={GITHUB[github.state]}
                  hollow={!signedIn}
                />
              )}
              {checking && <Fireflies />}
              <Button
                disabled={checking}
                onClick={() => {
                  setChecking(true);
                  void actions.checkGithub().finally(() => {
                    setChecking(false);
                  });
                }}
              >
                Check again
              </Button>
            </>
          }
        />
      </div>
    </SettingsSection>
  );
}
