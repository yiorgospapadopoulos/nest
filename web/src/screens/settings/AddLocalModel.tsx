import { useCallback, useEffect, useId, useState } from "react";
import type { CheckResult, FoundModel, FoundModels } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { startLabel } from "../../store/local.ts";
import { Sheet } from "../../ui/Sheet.tsx";
import {
  addTitle,
  checkedLine,
  downloadedLine,
  foundTag,
  foundWarnings,
  localPlace,
} from "./accountText.ts";

type Tab = "find" | "address";

const keyOf = (model: FoundModel) => `${model.address}/${model.model}`;

/**
 * Add local model (B106, D129), as the Mac's sheet: Find on the Mac lists the models its
 * servers run now (those good at tools ticked) and the ones downloaded, with Start where Nest
 * can start their app; Enter address checks a server with an optional key. Add sends each
 * server's ticked models.
 */
export function AddLocalModel({ onClose }: { onClose: () => void }) {
  const { actions } = useStore();
  const [tab, setTab] = useState<Tab>("find");
  const [found, setFound] = useState<FoundModels | null>(null);
  // It looks as soon as it opens.
  const [finding, setFinding] = useState(true);
  const [address, setAddress] = useState("");
  const [key, setKey] = useState("");
  const [check, setCheck] = useState<{ result: CheckResult; address: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const [adding, setAdding] = useState(false);
  const [chosen, setChosen] = useState<Set<string>>(new Set());

  // A model too big for the Mac's memory is left to the user to tick.
  const choose = useCallback((models: FoundModel[], good: (m: FoundModel) => boolean) => {
    setChosen((before) => {
      const next = new Set(before);
      for (const m of models) {
        if (!m.added && m.memory_warning === null && good(m)) next.add(keyOf(m));
      }
      return next;
    });
  }, []);

  const showFound = useCallback(
    (result: FoundModels | null) => {
      setFinding(false);
      if (result === null) return;
      setFound(result);
      choose(result.running, (m) => m.tools === "good");
    },
    [choose],
  );

  const find = () => {
    setFinding(true);
    return actions.findLocalModels().then(showFound);
  };

  useEffect(() => {
    void actions.findLocalModels().then(showFound);
  }, [actions, showFound]);

  const typedKey = key.trim() === "" ? null : key.trim();
  const checkAddress = async () => {
    const typed = address.trim();
    if (typed === "") return;
    setChecking(true);
    const result = await actions.checkLocalServer(typed, typedKey);
    setChecking(false);
    if (result === null) return;
    setCheck({ result, address: typed });
    choose(result.models, (m) => m.tools === "good" || m.tools === "unknown");
  };

  const choices =
    tab === "find" ? (found?.running ?? []) : check?.result.ok === true ? check.result.models : [];
  const picked = choices.filter((m) => !m.added && chosen.has(keyOf(m)));

  const add = async () => {
    setAdding(true);
    const done = await actions.addLocalModels(picked, tab === "address" ? typedKey : null);
    setAdding(false);
    if (done) onClose();
  };

  const toggle = (model: FoundModel) => {
    setChosen((before) => {
      const next = new Set(before);
      if (!next.delete(keyOf(model))) next.add(keyOf(model));
      return next;
    });
  };

  const line = check === null ? null : checkedLine(check.result, check.address);
  return (
    <Sheet
      title="Add local model"
      full
      onClose={onClose}
      leading={
        <button className="done l" onClick={onClose}>
          Cancel
        </button>
      }
      trailing={
        <button
          className="done"
          disabled={picked.length === 0 || adding}
          onClick={() => void add()}
        >
          {addTitle(picked.length)}
        </button>
      }
    >
      <div className="set addloc">
        <div className="mseg addseg" role="group" aria-label="Where to look">
          <button
            aria-pressed={tab === "find"}
            onClick={() => {
              setTab("find");
            }}
          >
            Find on the Mac
          </button>
          <button
            aria-pressed={tab === "address"}
            onClick={() => {
              setTab("address");
            }}
          >
            Enter address
          </button>
        </div>
        {tab === "find" ? (
          <>
            <div className="addnote">
              <span>
                Looked for running servers and in the LM Studio, Ollama and Hugging Face model
                folders.
              </span>
              <button className="lnk" disabled={finding} onClick={() => void find()}>
                {finding ? "Looking..." : "Look again"}
              </button>
            </div>
            <h3 className="pg-h">Running now</h3>
            <div className="lgrp">
              {found !== null && choices.length === 0 && (
                <p className="srow note">No model server is running on this Mac.</p>
              )}
              {choices.map((model) => (
                <FoundRow
                  key={keyOf(model)}
                  model={model}
                  on={model.added || chosen.has(keyOf(model))}
                  onToggle={() => {
                    toggle(model);
                  }}
                />
              ))}
            </div>
            {found !== null && found.downloaded.length > 0 && (
              <>
                <h3 className="pg-h">Downloaded, not running</h3>
                <div className="lgrp">
                  {found.downloaded.map((model) => (
                    <div key={model.path} className="srow addrow">
                      <span className="ucheck off" aria-hidden="true" />
                      <span className="slab">
                        <span className="dim">{model.name}</span>
                        <span className="hint">{downloadedLine(model)}</span>
                      </span>
                      {model.start !== null && (
                        <button
                          className="b"
                          onClick={() => {
                            const app = model.start;
                            if (app === null) return;
                            void actions.startLocalServer(app).then(find);
                          }}
                        >
                          {startLabel(model.start)}
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        ) : (
          <>
            <AddressFields
              address={address}
              typedKey={key}
              checking={checking}
              onAddress={setAddress}
              onKey={setKey}
              onCheck={() => void checkAddress()}
            />
            {line !== null && (
              <p className={line.ok ? "addline ok" : "addline bad"} role="status">
                {line.text}
              </p>
            )}
            {choices.length > 0 && (
              <div className="lgrp">
                {choices.map((model) => (
                  <FoundRow
                    key={keyOf(model)}
                    model={model}
                    on={model.added || chosen.has(keyOf(model))}
                    onToggle={() => {
                      toggle(model);
                    }}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}

/** A model a server offers: its tick, name and where it runs, its warnings and its tag. */
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
    <div className="srow addrow">
      <button
        className="ucheck"
        role="checkbox"
        aria-checked={on}
        aria-label={`Add ${model.name}`}
        disabled={model.added}
        onClick={onToggle}
      />
      <span className="slab">
        <span>{model.name}</span>
        <span className="hint">{localPlace(model)}</span>
        {foundWarnings(model).map((warning) => (
          <span key={warning} className="hint acwarn">
            {warning}
          </span>
        ))}
      </span>
      {tag !== null && <span className={model.added ? "sval" : "sst ok"}>{tag}</span>}
    </div>
  );
}

function AddressFields({
  address,
  typedKey,
  checking,
  onAddress,
  onKey,
  onCheck,
}: {
  address: string;
  typedKey: string;
  checking: boolean;
  onAddress: (text: string) => void;
  onKey: (text: string) => void;
  onCheck: () => void;
}) {
  const addressId = useId();
  const keyId = useId();
  return (
    <form
      className="addform"
      onSubmit={(event) => {
        event.preventDefault();
        onCheck();
      }}
    >
      <label htmlFor={addressId}>Where the model runs</label>
      <div className="addfield">
        <input
          id={addressId}
          className="cfg-search"
          placeholder="localhost:8080"
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          inputMode="url"
          value={address}
          onChange={(event) => {
            onAddress(event.target.value);
          }}
        />
        <button className="b" type="submit" disabled={checking || address.trim() === ""}>
          {checking ? "Checking..." : "Check"}
        </button>
      </div>
      <label htmlFor={keyId}>Key, only if the server asks for one</label>
      <input
        id={keyId}
        className="cfg-search"
        type="password"
        autoComplete="off"
        placeholder="None"
        value={typedKey}
        onChange={(event) => {
          onKey(event.target.value);
        }}
      />
    </form>
  );
}
