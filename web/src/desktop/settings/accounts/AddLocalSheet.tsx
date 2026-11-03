import { useCallback, useEffect, useState } from "react";
import type { CheckResult, FoundModel, FoundModels } from "../../../api/types.ts";
import {
  addTitle,
  checkedLine,
  downloadedLine,
  foundTag,
  foundWarnings,
  localPlace,
} from "../../../screens/settings/accountText.ts";
import { useStore } from "../../../store/context.ts";
import { startLabel } from "../../../store/local.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Icon } from "../../../ui/Icon.tsx";
import { SheetFrame } from "../../sheets/SheetFrame.tsx";
import { Button, TextField } from "../../ui/controls.tsx";
import { CheckBox, Failure, WarningLine } from "../rows.tsx";
import { SegmentPicker, StatusLabel } from "../config/parts.tsx";
import { isChosen, modelKey, picked, withFound, type AddTab } from "./addLocal.ts";

const TABS: readonly (readonly [AddTab, string])[] = [
  ["find", "Find on this computer"],
  ["address", "Enter address"],
];

/**
 * Add local model (B106), as LocalModelsSection.swift's AddLocalSheet: Find on this
 * computer lists the running servers' models (those good at tools chosen) and the
 * downloaded ones with Start; Enter address checks a server, with an optional key. Add
 * sends each server's chosen models.
 */
export function AddLocalSheet({ onClose }: { onClose: () => void }) {
  const { state, actions } = useStore();
  const [tab, setTab] = useState<AddTab>("find");
  const [found, setFound] = useState<FoundModels | null>(null);
  // It looks as soon as it opens.
  const [finding, setFinding] = useState(true);
  const [address, setAddress] = useState("");
  const [key, setKey] = useState("");
  const [check, setCheck] = useState<{ result: CheckResult; address: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const [adding, setAdding] = useState(false);
  const [chosen, setChosen] = useState<Set<string>>(new Set());

  const show = useCallback((result: FoundModels | null) => {
    setFinding(false);
    if (result === null) return;
    setFound(result);
    setChosen((before) => withFound(before, result.running, "find"));
  }, []);
  useEffect(() => {
    void actions.findLocalModels().then(show);
  }, [actions, show]);
  const find = () => {
    setFinding(true);
    void actions.findLocalModels().then(show);
  };

  const typedKey = key.trim() === "" ? null : key.trim();
  const checkAddress = () => {
    const typed = address.trim();
    if (typed === "" || checking) return;
    setChecking(true);
    void actions.checkLocalServer(typed, typedKey).then((result) => {
      setChecking(false);
      if (result === null) return;
      setCheck({ result, address: typed });
      setChosen((before) => withFound(before, result.models, "address"));
    });
  };

  const choices =
    tab === "find" ? (found?.running ?? []) : check?.result.ok === true ? check.result.models : [];
  const toAdd = picked(chosen, choices);
  const add = () => {
    if (toAdd.length === 0 || adding) return;
    setAdding(true);
    void actions.addLocalModels(toAdd, tab === "address" ? typedKey : null).then((done) => {
      setAdding(false);
      if (done) onClose();
    });
  };
  const toggle = (model: FoundModel) => {
    if (model.added) return;
    setChosen((before) => {
      const next = new Set(before);
      if (!next.delete(modelKey(model))) next.add(modelKey(model));
      return next;
    });
  };
  const line = check === null ? null : checkedLine(check.result, check.address);
  const rows = choices.map((model) => (
    <FoundRow
      key={modelKey(model)}
      model={model}
      on={isChosen(chosen, model)}
      onToggle={() => {
        toggle(model);
      }}
    />
  ));

  return (
    <SheetFrame
      title="Add local model"
      width={560}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" disabled={toAdd.length === 0 || adding} onClick={add}>
            {addTitle(toAdd.length)}
          </Button>
        </>
      }
    >
      <div className="dka-add">
        <SegmentPicker label="Where to look" options={TABS} value={tab} onChange={setTab} />
        {tab === "find" ? (
          <>
            <div className="dka-add-note">
              <span>
                Looked for running servers and in the LM Studio, Ollama and Hugging Face model
                folders.
              </span>
              {finding && <Fireflies />}
              <Button kind="plain" disabled={finding} onClick={find}>
                <Icon name="restart" />
                Look again
              </Button>
            </div>
            <div className="dka-add-list">
              <h3 className="dka-add-h">Running now</h3>
              {found !== null && choices.length === 0 && (
                <p className="dka-add-row none">No model server is running on this computer.</p>
              )}
              {rows}
            </div>
            {found !== null && found.downloaded.length > 0 && (
              <div className="dka-add-list">
                <h3 className="dka-add-h">Downloaded, not running</h3>
                {found.downloaded.map((model) => (
                  <div key={model.path} className="dka-add-row">
                    <span className="dka-off">
                      <CheckBox on={false} />
                    </span>
                    <span className="dka-add-t">
                      <span className="dim">{model.name}</span>
                      <span className="meta">{downloadedLine(model)}</span>
                    </span>
                    {model.start !== null && (
                      <Button
                        disabled={state.local.starting.includes(model.start)}
                        onClick={() => {
                          const app = model.start;
                          if (app !== null) void actions.startLocalServer(app).then(find);
                        }}
                      >
                        {startLabel(model.start)}
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            <form
              className="dka-add-field"
              onSubmit={(event) => {
                event.preventDefault();
                checkAddress();
              }}
            >
              <span className="dka-add-label">Where the model runs</span>
              <span className="dka-add-line">
                <TextField
                  label="Where the model runs"
                  placeholder="localhost:8080"
                  value={address}
                  onChange={setAddress}
                  autoFocus
                />
                {checking && <Fireflies />}
                <Button type="submit" disabled={address.trim() === "" || checking}>
                  Check
                </Button>
              </span>
            </form>
            <label className="dka-add-field">
              <span className="dka-add-label">Key, only if the server asks for one</span>
              <TextField
                type="password"
                label="Key, only if the server asks for one"
                placeholder="None"
                value={key}
                onChange={setKey}
              />
            </label>
            {line !== null &&
              (line.ok ? (
                <StatusLabel tone="review" label={line.text} />
              ) : (
                <Failure text={line.text} />
              ))}
            {rows.length > 0 && <div className="dka-add-list">{rows}</div>}
          </>
        )}
      </div>
    </SheetFrame>
  );
}

/** A model a server offers: its checkbox, name and where it runs, its warnings and tag. */
function FoundRow({
  model,
  on,
  onToggle,
}: {
  model: FoundModel;
  on: boolean;
  onToggle: () => void;
}) {
  const tag = foundTag(model);
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={on}
      aria-label={`Add ${model.name}`}
      className="dka-add-row pick"
      disabled={model.added}
      onClick={onToggle}
    >
      <span className={model.added ? "dka-off" : undefined}>
        <CheckBox on={on} />
      </span>
      <span className="dka-add-t">
        <span>{model.name}</span>
        <span className="meta">{localPlace(model)}</span>
        {foundWarnings(model).map((warning) => (
          <WarningLine key={warning} text={warning} />
        ))}
      </span>
      {tag !== null && <span className={model.added ? "meta" : "good"}>{tag}</span>}
    </button>
  );
}
