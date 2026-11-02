import { useState } from "react";
import type { LocalApp, LocalEngine, LocalModel } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { startLabel } from "../../store/local.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";
import { ChoiceSheet } from "../pixies/ChoiceSheet.tsx";
import { Confirm } from "../pixies/Confirm.tsx";
import { Mark } from "./AccountRows.tsx";
import { localEngineName, localNote, localPlace, localState } from "./accountText.ts";
import { AddLocalModel } from "./AddLocalModel.tsx";
import { Loading, Section, Status } from "./rows.tsx";

const ENGINES: LocalEngine[] = ["claude", "codex"];

// The apps Nest can start, by the label the daemon gives a model's app.
const APPS: Record<string, LocalApp> = { "LM Studio": "lmstudio", Ollama: "ollama" };

/**
 * Settings > Accounts' local models (B106, D129): each added model with where it runs and
 * its state, tapped for Start and Remove; the engine local chats run on; Add local model.
 */
export function LocalModels() {
  const { state, actions } = useStore();
  const [acting, setActing] = useState<LocalModel | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [adding, setAdding] = useState(false);
  const list = state.local.list;
  if (list === null) return <Loading title="Local models" />;
  const has = list.models.length > 0;
  return (
    <Section title="Local models" className="acct" mark={<Mark name="local" />}>
      {list.models.map((model) => {
        const status = localState(model);
        return (
          <button
            key={model.id}
            className="srow acloc"
            onClick={() => {
              setActing(model);
            }}
          >
            <span className="slab">
              <span>{model.name}</span>
              <span className="hint">{localPlace(model)}</span>
              {model.memory_warning !== null && (
                <span className="hint acwarn">{model.memory_warning}</span>
              )}
            </span>
            <Status tone={status.tone} label={status.label} />
          </button>
        );
      })}
      {has && (
        <button
          className="srow slink"
          onClick={() => {
            setChoosing(true);
          }}
        >
          <span className="slab">Local chats run on</span>
          <span className="sval">{localEngineName(list.engine)}</span>
          <Icon name="chevr" className="schev" />
        </button>
      )}
      <button
        className="srow slink acadd"
        onClick={() => {
          setAdding(true);
        }}
      >
        <span className="cn">
          <Icon name="plus" />
          <span>Add local model</span>
        </span>
      </button>
      {has && <p className="srow note">{localNote(list.engine)}</p>}
      {acting !== null && (
        <ModelActions
          model={acting}
          onClose={() => {
            setActing(null);
          }}
        />
      )}
      {choosing && (
        <ChoiceSheet
          title="Local chats run on"
          choices={ENGINES.map((engine) => ({ key: engine, label: localEngineName(engine) }))}
          current={list.engine}
          onPick={(engine) => void actions.setLocalEngine(engine as LocalEngine)}
          onClose={() => {
            setChoosing(false);
          }}
        />
      )}
      {adding && (
        <AddLocalModel
          onClose={() => {
            setAdding(false);
          }}
        />
      )}
    </Section>
  );
}

/** A model's menu: Start its app while its server is not running, and Remove, which asks. */
function ModelActions({ model, onClose }: { model: LocalModel; onClose: () => void }) {
  const { state, actions } = useStore();
  const [removing, setRemoving] = useState(false);
  const app = model.app === null ? undefined : APPS[model.app];
  if (removing) {
    return (
      <Confirm
        title={`Remove ${model.name}?`}
        about="Chats on it keep their history; choose another model to go on with them."
        action="Remove"
        onConfirm={() => void actions.removeLocalModel(model.id)}
        onClose={onClose}
      />
    );
  }
  return (
    <ActionSheet
      label={`Actions for ${model.name}`}
      title={
        <>
          <b>{model.name}</b>
          {model.weak_reason ?? ""}
        </>
      }
      onClose={onClose}
    >
      {!model.running && app !== undefined && (
        <button
          className="asi"
          role="menuitem"
          disabled={state.local.starting.includes(app)}
          onClick={() => {
            onClose();
            void actions.startLocalServer(app);
          }}
        >
          <Icon name="play" />
          <span>{startLabel(app)}</span>
        </button>
      )}
      <button
        className="asi dng"
        role="menuitem"
        onClick={() => {
          setRemoving(true);
        }}
      >
        <Icon name="trash" />
        <span>Remove</span>
      </button>
    </ActionSheet>
  );
}
