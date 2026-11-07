import { useEffect, useState } from "react";
import { useStore } from "../../../store/context.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Button, TextField } from "../../ui/controls.tsx";
import { SettingsSection } from "../rows.tsx";
import { StatusLabel } from "../config/parts.tsx";
import { Confirm } from "../../sheets/Alert.tsx";
import { useSettingsChange } from "../config/util.ts";
import type { EngineSetup } from "./engineSetup.ts";
import { AccountsHeader, AccountsSymbol } from "./parts.tsx";

/** The engines past Claude and Codex (B107), one compact row each, as one section. */
export function MoreEnginesSection({ setups }: { setups: EngineSetup[] }) {
  return (
    <SettingsSection bare>
      <AccountsHeader title="More engines" mark={<AccountsSymbol name="agent" />} />
      <MoreEngineRows setups={setups} />
    </SettingsSection>
  );
}

/** The rows themselves, as Settings > Accounts and the setup guide's Engine step show them. */
export function MoreEngineRows({ setups }: { setups: EngineSetup[] }) {
  const { actions } = useStore();
  // A sign-in in a terminal sends no event, so the engines are asked again on the way back.
  useEffect(() => {
    const back = () => {
      if (document.visibilityState === "visible") void actions.loadProviders(true);
    };
    window.addEventListener("focus", back);
    return () => {
      window.removeEventListener("focus", back);
    };
  }, [actions]);
  return (
    <div className="dka-rows" role="group" aria-label="More engines">
      {setups.map((setup) => (
        <MoreEngineRow key={setup.name} setup={setup} />
      ))}
    </div>
  );
}

/**
 * An engine's name with its version under it, its labels and the git warning mark, then
 * its state and its one action.
 */
function MoreEngineRow({ setup }: { setup: EngineSetup }) {
  const { actions } = useStore();
  const change = useSettingsChange();
  const [addingKey, setAddingKey] = useState(false);
  const [key, setKey] = useState("");
  const [removingKey, setRemovingKey] = useState(false);
  const [warning, setWarning] = useState(false);

  // The key goes to the daemon only, which keeps it in the keyring; the field empties.
  const saveKey = () => {
    const typed = key.trim();
    if (typed === "") return;
    setKey("");
    setAddingKey(false);
    void actions.saveEngineKey(setup.name, typed);
  };
  const copy = (command: string) => {
    change("Could not copy the command", async () => {
      await navigator.clipboard.writeText(command);
      actions.toast("Copied");
    });
  };

  const action = setup.action;
  return (
    <div className="dka-engine" role="group" aria-label={setup.title}>
      <span className="dka-engine-t">
        <span className="dka-engine-n">
          <b>{setup.title}</b>
          {setup.labels.map((label) => (
            <span key={label} className="dka-label">
              {label}
            </span>
          ))}
          {setup.gitWarning !== null && (
            <span
              className="dka-warnmark"
              role="img"
              aria-label={setup.gitWarning}
              onPointerEnter={() => {
                setWarning(true);
              }}
              onPointerLeave={() => {
                setWarning(false);
              }}
            >
              <svg viewBox="0 0 12 12" aria-hidden="true">
                <path d="M6 1.5 11 10.5H1z" />
                <path d="M6 5v2.4M6 8.9v.1" />
              </svg>
              {/* A tooltip does not show over this row, so the warning opens on hover. */}
              {warning && (
                <span className="dka-tip" role="tooltip">
                  {setup.gitWarning}
                </span>
              )}
            </span>
          )}
        </span>
        {setup.version !== null && <span className="dka-version">{setup.version}</span>}
        {setup.failure !== null && <span className="dka-meta clamp">{setup.failure}</span>}
      </span>
      <span className="dka-engine-c">
        {setup.installing && <Fireflies />}
        <StatusLabel
          tone={setup.ready ? "review" : "done"}
          label={setup.state}
          hollow={!setup.ready}
        />
        {action.kind === "install" && (
          <Button
            kind="primary"
            onClick={() => {
              void actions.installEngine(setup.name);
            }}
          >
            {action.again ? "Install again" : "Install"}
          </Button>
        )}
        {/* This app cannot start a terminal running a command: the login is copied to run. */}
        {action.kind === "signIn" && (
          <Button
            onClick={() => {
              copy(action.command);
            }}
          >
            Copy sign-in command
          </Button>
        )}
        {action.kind === "addKey" &&
          (addingKey ? (
            <form
              className="dka-key"
              onSubmit={(event) => {
                event.preventDefault();
                saveKey();
              }}
            >
              <TextField
                type="password"
                label={`${setup.title} API key`}
                placeholder={action.placeholder}
                value={key}
                onChange={setKey}
                autoFocus
              />
              <Button type="submit" kind="primary" disabled={key.trim() === ""}>
                Save
              </Button>
            </form>
          ) : (
            <Button
              kind="primary"
              onClick={() => {
                setAddingKey(true);
              }}
            >
              Add key
            </Button>
          ))}
        {action.kind === "removeKey" && (
          <Button
            onClick={() => {
              setRemovingKey(true);
            }}
          >
            Remove key
          </Button>
        )}
      </span>
      {removingKey && (
        <Confirm
          title={`Remove the ${setup.title} key?`}
          message={`${setup.title} chats cannot run until you save a key again.`}
          action="Remove"
          destructive
          onConfirm={() => void actions.removeEngineKey(setup.name)}
          onClose={() => {
            setRemovingKey(false);
          }}
        />
      )}
    </div>
  );
}
