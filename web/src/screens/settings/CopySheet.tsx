import { useState, type ReactNode } from "react";
import type { CopyPreview, EngineId } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Sheet } from "../../ui/Sheet.tsx";
import { copyIntro, copySections, copyTitle, replaceWarning } from "./configText.ts";

/** The done line after a copy, with its Undo. */
export interface CopyDone {
  engine: EngineId;
  summary: string;
  undoId: string;
}

interface Props {
  engine: EngineId;
  // The engine's display name.
  name: string;
  preview: CopyPreview;
  onDone: (done: CopyDone) => void;
  onClose: () => void;
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="cfg-part">
      <h3>{title}</h3>
      <div>{children}</div>
    </div>
  );
}

/**
 * What copying an engine's setup to Shared adds, replaces and leaves (B97): skills and MCP
 * servers are added, the instructions replaced unless kept, with Compare (B102 item 31).
 */
export function CopySheet({ engine, name, preview, onDone, onClose }: Props) {
  const { actions } = useStore();
  const [keep, setKeep] = useState(false);
  const [compare, setCompare] = useState<{ engine: string; shared: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const instructions = preview.instructions;

  const toggleCompare = async (files: NonNullable<CopyPreview["instructions"]>) => {
    if (compare !== null) {
      setCompare(null);
      return;
    }
    const mine = await actions.readConfigFile(files.engine_path);
    const shared = mine === null ? null : await actions.readConfigFile(files.shared_path);
    if (mine !== null && shared !== null) setCompare({ engine: mine.text, shared: shared.text });
  };

  const copy = async () => {
    setBusy(true);
    const done = await actions.copyToShared(engine, instructions !== null && !keep);
    setBusy(false);
    if (done !== null) onDone({ engine, summary: done.summary, undoId: done.undo_id });
  };

  return (
    <Sheet
      title={copyTitle(name)}
      onClose={onClose}
      footer={
        <div className="cfg-acts">
          <button className="b" onClick={onClose}>
            Cancel
          </button>
          <button className="b b-pri" disabled={busy} onClick={() => void copy()}>
            Copy to Shared
          </button>
        </div>
      }
    >
      <div className="cfg-copy">
        <p className="cfg-about">{copyIntro(preview)}</p>
        {instructions !== null && (
          <Part title="Instructions">
            <p className={keep ? "cfg-dim" : "cfg-warn"}>{replaceWarning(name)}</p>
            <div className="cfg-acts start">
              <button className="b" onClick={() => void toggleCompare(instructions)}>
                {compare === null ? "Compare the two files" : "Hide the files"}
              </button>
              <label className="cfg-check">
                <input
                  type="checkbox"
                  checked={keep}
                  onChange={() => {
                    setKeep(!keep);
                  }}
                />
                Keep instructions as they are
              </label>
            </div>
            {compare !== null && (
              <div className="cfg-cmp">
                <ComparePane title={`${name}'s`} text={compare.engine} />
                <ComparePane title="Shared now" text={compare.shared} />
              </div>
            )}
          </Part>
        )}
        {copySections(preview, name).map((section) => (
          <Part key={section.title} title={section.title}>
            {section.lead !== null && (
              <p>
                <b>{section.lead}</b>
                {section.names !== null && <span> {section.names}</span>}
              </p>
            )}
            {section.notes.map((note) => (
              <p key={note} className="cfg-dim">
                {note}
              </p>
            ))}
          </Part>
        ))}
      </div>
    </Sheet>
  );
}

function ComparePane({ title, text }: { title: string; text: string }) {
  return (
    <div className="cfg-pane">
      <h4>{title}</h4>
      <pre className={text === "" ? "cfg-dim" : undefined}>{text === "" ? "Empty" : text}</pre>
    </div>
  );
}
