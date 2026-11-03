import { useEffect, useState } from "react";
import type { LocalApp, LocalModel } from "../../../api/types.ts";
import { localNote, localPlace, localState } from "../../../screens/settings/accountText.ts";
import { useStore } from "../../../store/context.ts";
import { startLabel } from "../../../store/local.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Icon } from "../../../ui/Icon.tsx";
import { Button } from "../../ui/controls.tsx";
import { Menu } from "../../ui/Menu.tsx";
import { SettingsListRow, SettingsSection } from "../rows.tsx";
import { Glyph, StatusLabel, type StatusTone } from "../config/parts.tsx";
import { Confirm } from "../../sheets/Alert.tsx";
import { AddLocalSheet } from "./AddLocalSheet.tsx";
import { AccountsHeader, AccountsSymbol, MoreGlyph } from "./parts.tsx";

// The apps Nest can start, by the name the daemon gives a model's app.
const APPS: Record<string, LocalApp> = { "LM Studio": "lmstudio", Ollama: "ollama" };

const TONES: Record<ReturnType<typeof localState>["tone"], StatusTone> = {
  ok: "review",
  wait: "waiting",
  bad: "failed",
  run: "running",
  idle: "done",
};

/**
 * Settings > Accounts' local models (B106), as LocalModelsSection.swift: each added model
 * with where it runs and its state, Start for a server that is not running, Remove in its
 * menu; then Add local model and a note on the engine local chats run on.
 */
export function LocalModelsSection() {
  const { state, actions } = useStore();
  const [adding, setAdding] = useState(false);
  useEffect(() => {
    void actions.loadLocalModels();
  }, [actions]);
  const list = state.local.list;
  const models = list?.models ?? [];
  const has = models.length > 0;
  return (
    <SettingsSection bare>
      <AccountsHeader title="Local models" mark={<AccountsSymbol name="laptop" />} />
      {has && (
        <div className="dka-rows">
          {models.map((model) => (
            <LocalModelRow key={model.id} model={model} />
          ))}
        </div>
      )}
      <div className={has ? "dka-tools" : "dka-tools first"}>
        <Button
          onClick={() => {
            setAdding(true);
          }}
        >
          <Icon name="plus" />
          Add local model
        </Button>
      </div>
      {has && list !== null && <p className="dka-note">{localNote(list.engine)}</p>}
      {adding && (
        <AddLocalSheet
          onClose={() => {
            setAdding(false);
          }}
        />
      )}
    </SettingsSection>
  );
}

function LocalModelRow({ model }: { model: LocalModel }) {
  const { state, actions } = useStore();
  const [removing, setRemoving] = useState(false);
  const status = localState(model);
  const app = model.app === null ? undefined : APPS[model.app];
  const starting = app !== undefined && state.local.starting.includes(app);
  return (
    <div title={model.weak_reason ?? undefined}>
      <SettingsListRow
        title={model.name}
        detail={localPlace(model)}
        warning={model.memory_warning}
        leading={
          <span className="dks-badge" aria-hidden="true">
            <Glyph name="chip" />
          </span>
        }
        trailing={
          <>
            <StatusLabel
              tone={TONES[status.tone]}
              label={status.label}
              hollow={TONES[status.tone] !== "review"}
            />
            {!model.running && app !== undefined && (
              <>
                {starting && <Fireflies />}
                <Button
                  disabled={starting}
                  onClick={() => {
                    void actions.startLocalServer(app);
                  }}
                >
                  {startLabel(app)}
                </Button>
              </>
            )}
            <Menu
              label={`Actions for ${model.name}`}
              align="end"
              items={[
                {
                  title: "Remove",
                  danger: true,
                  onSelect: () => {
                    setRemoving(true);
                  },
                },
              ]}
            >
              {(trigger) => (
                <button
                  {...trigger}
                  type="button"
                  className="dka-menu"
                  aria-label={`Actions for ${model.name}`}
                  title="More"
                >
                  <MoreGlyph />
                </button>
              )}
            </Menu>
          </>
        }
      />
      {removing && (
        <Confirm
          title={`Remove ${model.name}?`}
          message="Chats on it keep their history; choose another model to go on with them."
          action="Remove"
          destructive
          onConfirm={() => void actions.removeLocalModel(model.id)}
          onClose={() => {
            setRemoving(false);
          }}
        />
      )}
    </div>
  );
}
