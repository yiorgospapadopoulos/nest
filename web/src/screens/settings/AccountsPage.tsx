import { useEffect, useState } from "react";
import type { EngineState, GithubAccount, GithubState, ProviderInfo } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { EngineAccounts, Mark } from "./AccountRows.tsx";
import { LocalModels } from "./LocalModels.tsx";
import { Loading, Row, Section, Status, type StatusTone } from "./rows.tsx";

const GITHUB: Record<GithubState, { tone: StatusTone; label: string }> = {
  signed_in: { tone: "ok", label: "Signed in" },
  signed_out: { tone: "wait", label: "Signed out" },
  unavailable: { tone: "bad", label: "gh not installed" },
};

// Claude's and Codex's own sections come first; every other engine is a row of More engines.
const OWN_SECTIONS = new Set(["claude", "codex"]);

/**
 * Each engine's accounts (B98, D124), the other engines (B107), the local models (B106),
 * first when the user chose them only, and the GitHub login, as the Mac has them. Adding an
 * account and signing in happen on the Mac; Nest keeps only an engine's API key, in its
 * Keychain.
 */
export function AccountsPage() {
  const { state, actions } = useStore();
  const { github } = state.settings;
  const engines = (state.providers ?? []).filter((p) => !OWN_SECTIONS.has(p.name));
  const local = state.local.list;
  // With local models, signing in to an engine is a choice, not a need (B106).
  const optional = local !== null && (local.local_only || local.models.length > 0);
  const localFirst = local?.local_only === true;

  useEffect(() => {
    void actions.loadAccounts();
    void actions.loadLocalModels();
  }, [actions]);

  return (
    <>
      {localFirst && <LocalModels />}
      <EngineAccounts provider="claude" optional={optional} />
      <EngineAccounts provider="codex" optional={optional} />
      {engines.length > 0 && <MoreEngines engines={engines} />}
      {!localFirst && <LocalModels />}
      {github === null ? <Loading title="GitHub" /> : <GitHub account={github} />}
    </>
  );
}

const ENGINE_STATE: Record<EngineState, { tone: StatusTone; label: string }> = {
  ready: { tone: "ok", label: "Ready" },
  not_installed: { tone: "wait", label: "Not installed" },
  installing: { tone: "run", label: "Installing" },
  install_failed: { tone: "bad", label: "Install failed" },
};

/** The state beside an engine: why it cannot run, else whether it is signed in. */
function engineStatus(engine: ProviderInfo): { tone: StatusTone; label: string } {
  // Nest does not fetch an engine the user installs themselves: it was not found on PATH.
  if (engine.state === "not_installed" && !engine.installable) {
    return { tone: "wait", label: "Not on PATH: install it yourself" };
  }
  if (engine.state !== "ready" || engine.signed_in === true) return ENGINE_STATE[engine.state];
  if (engine.sign_in === "api_key") return { tone: "wait", label: "No key" };
  return CODEX_STATE[String(engine.signed_in) as keyof typeof CODEX_STATE];
}

const GIT_WARNING =
  "Nest cannot block this engine's git commands, so it may commit or push on its own.";

/** The engines past Claude and Codex (B107), one compact row each, as one section. */
function MoreEngines({ engines }: { engines: ProviderInfo[] }) {
  return (
    <Section title="More engines" className="acct" mark={<Mark name="more" />}>
      {engines.map((engine) => (
        <Engine key={engine.name} engine={engine} />
      ))}
    </Section>
  );
}

/**
 * An engine Nest runs over ACP: its name, version and labels, a warning mark when Nest
 * cannot block its git commands, its state and its one action.
 */
function Engine({ engine }: { engine: ProviderInfo }) {
  const [addingKey, setAddingKey] = useState(false);
  const status = engineStatus(engine);
  const needsKey =
    engine.state === "ready" && engine.sign_in === "api_key" && engine.signed_in !== true;
  return (
    <>
      <Row
        label={
          <>
            <span className="eng-name">
              <span>{engine.display_name}</span>
              {!engine.git_guard && (
                <span className="eng-warn" role="img" aria-label={GIT_WARNING} title={GIT_WARNING}>
                  ⚠
                </span>
              )}
            </span>
            {engine.version !== null && <span className="hint mono">{engine.version}</span>}
          </>
        }
      >
        <Status tone={status.tone} label={status.label} />
        <EngineAction
          engine={engine}
          addingKey={addingKey}
          onAddKey={() => {
            setAddingKey(true);
          }}
        />
      </Row>
      {engine.state === "install_failed" && engine.state_detail !== null && (
        <p className="srow note">{engine.state_detail}</p>
      )}
      {needsKey && addingKey && <KeyField engine={engine} />}
    </>
  );
}

/** The row's one action: install, add or remove a key, or copy the sign-in command. */
function EngineAction({
  engine,
  addingKey,
  onAddKey,
}: {
  engine: ProviderInfo;
  addingKey: boolean;
  onAddKey: () => void;
}) {
  const { actions } = useStore();
  const [busy, setBusy] = useState(false);
  const name = engine.display_name;
  const run = (action: () => Promise<unknown>) => {
    setBusy(true);
    void action().finally(() => {
      setBusy(false);
    });
  };
  if (engine.state !== "ready") {
    const canInstall =
      engine.installable && (engine.state === "not_installed" || engine.state === "install_failed");
    if (!canInstall) return null;
    return (
      <button
        className="b"
        aria-label={`Install ${name}`}
        disabled={busy}
        onClick={() => {
          run(() => actions.installEngine(engine.name));
        }}
      >
        {engine.state === "install_failed" ? "Install again" : "Install"}
      </button>
    );
  }
  if (engine.sign_in === "api_key") {
    if (engine.signed_in === true) {
      return (
        <button
          className="b"
          aria-label={`Remove the ${name} API key`}
          disabled={busy}
          onClick={() => {
            run(() => actions.removeEngineKey(engine.name));
          }}
        >
          Remove key
        </button>
      );
    }
    return addingKey ? null : (
      <button className="b" aria-label={`Add a ${name} API key`} onClick={onAddKey}>
        Add key
      </button>
    );
  }
  if (engine.sign_in === "terminal" && engine.signed_in !== true && engine.login_command !== null) {
    return <CopyLogin command={engine.login_command} name={name} />;
  }
  return null;
}

/** A key pasted here goes to the Mac's Keychain. */
function KeyField({ engine }: { engine: ProviderInfo }) {
  const { actions } = useStore();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const name = engine.display_name;
  const save = () => {
    const typed = key.trim();
    if (typed === "") return;
    setBusy(true);
    void actions.saveEngineKey(engine.name, typed).then((saved) => {
      setBusy(false);
      if (saved) setKey("");
    });
  };
  return (
    <form
      className="srow"
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <input
        className="cfg-search"
        type="password"
        autoComplete="off"
        aria-label={`${name} API key`}
        placeholder={`Paste your ${name} API key`}
        value={key}
        onChange={(event) => {
          setKey(event.target.value);
        }}
      />
      <button className="b b-pri" type="submit" disabled={busy || key.trim() === ""}>
        Save
      </button>
    </form>
  );
}

/** The phone cannot run Terminal: the engine's login command is copied, to run on the Mac. */
function CopyLogin({ command, name }: { command: string; name: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard.writeText(command).then(
      () => {
        setCopied(true);
      },
      () => {
        setCopied(false);
      },
    );
  };
  return (
    <button className="b" aria-label={`Copy the ${name} sign-in command`} onClick={copy}>
      {copied ? "Copied" : "Copy sign-in command"}
    </button>
  );
}

const CODEX_STATE = {
  true: { tone: "ok", label: "Signed in" },
  false: { tone: "wait", label: "Signed out" },
  null: { tone: "idle", label: "Not checked" },
} as const;

function GitHub({ account }: { account: GithubAccount }) {
  const { actions } = useStore();
  const [checking, setChecking] = useState(false);
  const status = GITHUB[account.state];
  return (
    <Section title="GitHub" className="acct" mark={<Mark name="gh" />}>
      <Row label={account.login ?? "GitHub"}>
        <Status tone={status.tone} label={status.label} />
        <button
          className="b"
          disabled={checking}
          onClick={() => {
            setChecking(true);
            void actions.checkGithub().finally(() => {
              setChecking(false);
            });
          }}
        >
          {checking ? "Checking..." : "Check again"}
        </button>
      </Row>
    </Section>
  );
}
