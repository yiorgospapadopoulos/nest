import { useState, type ReactNode } from "react";
import type { CopyPreview, EngineSection } from "../../../api/types.ts";
import {
  copyIntro,
  copySections,
  copyTitle,
  replaceWarning,
} from "../../../screens/settings/configText.ts";
import { useStore } from "../../../store/context.ts";
import { SheetFrame } from "../../sheets/SheetFrame.tsx";
import { Button } from "../../ui/controls.tsx";
import { Checkbox } from "./parts.tsx";
import { useSettingsChange } from "./util.ts";

/** The done line after a copy, with its Undo. */
export interface CopyDone {
  engine: string;
  summary: string;
  undoId: string;
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="dkc-part">
      <h3>{title}</h3>
      <div>{children}</div>
    </div>
  );
}

function ComparePane({ title, text }: { title: string; text: string }) {
  return (
    <div className="dkc-pane">
      <h4>{title}</h4>
      <pre className={text === "" ? "empty" : undefined}>{text === "" ? "Empty" : text}</pre>
    </div>
  );
}

/**
 * What copying an engine's setup to Shared adds, replaces and leaves, with Compare and
 * "Keep instructions as they are", as the Mac's CopySheet.
 */
export function CopySheet({
  engine,
  preview,
  onDone,
  onClose,
}: {
  engine: EngineSection;
  preview: CopyPreview;
  onDone: (done: CopyDone) => void;
  onClose: () => void;
}) {
  const { actions } = useStore();
  const change = useSettingsChange();
  const [keep, setKeep] = useState(false);
  const [compare, setCompare] = useState<{ engine: string; shared: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const instructions = preview.instructions;

  const toggleCompare = (files: NonNullable<CopyPreview["instructions"]>) => {
    if (compare !== null) {
      setCompare(null);
      return;
    }
    change("Could not read the instructions", async () => {
      const mine = await actions.readConfigFile(files.engine_path);
      const shared = mine === null ? null : await actions.readConfigFile(files.shared_path);
      if (mine !== null && shared !== null) setCompare({ engine: mine.text, shared: shared.text });
    });
  };

  const copy = () => {
    setBusy(true);
    void actions.copyToShared(engine.id, instructions !== null && !keep).then((done) => {
      setBusy(false);
      if (done !== null) onDone({ engine: engine.id, summary: done.summary, undoId: done.undo_id });
    });
  };

  return (
    <SheetFrame
      title={copyTitle(engine.name)}
      width={640}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" disabled={busy} onClick={copy}>
            Copy to Shared
          </Button>
        </>
      }
    >
      <p className="dkc-copy-intro">{copyIntro(preview)}</p>
      {instructions !== null && (
        <Part title="Instructions">
          <p className={keep ? "dim" : "warn"}>{replaceWarning(engine.name)}</p>
          <div className="dkc-copy-acts">
            <Button
              onClick={() => {
                toggleCompare(instructions);
              }}
            >
              {compare === null ? "Compare the two files" : "Hide the files"}
            </Button>
            <Checkbox
              on={keep}
              label="Keep instructions as they are"
              onToggle={() => {
                setKeep(!keep);
              }}
            />
          </div>
          {compare !== null && (
            <div className="dkc-compare">
              <ComparePane title={`${engine.name}'s`} text={compare.engine} />
              <ComparePane title="Shared now" text={compare.shared} />
            </div>
          )}
        </Part>
      )}
      {copySections(preview, engine.name).map((section) => (
        <Part key={section.title} title={section.title}>
          {section.lead !== null && (
            <p>
              <b>{section.lead}</b>
              {section.names !== null && ` ${section.names}`}
            </p>
          )}
          {section.notes.map((note) => (
            <p key={note} className="dim">
              {note}
            </p>
          ))}
        </Part>
      ))}
    </SheetFrame>
  );
}
