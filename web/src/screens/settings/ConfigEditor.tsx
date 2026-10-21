import { useEffect, useRef, useState } from "react";
import type { FileText } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Sheet } from "../../ui/Sheet.tsx";
import { EDITOR_FOOTER, shortPath } from "./configText.ts";

/** A file to edit: its path, the sheet's title and a note such as "skill". */
export interface EditTarget {
  path: string;
  title: string;
  note: string;
}

/**
 * A setup file in a sheet (B97, B102 item 31). Saving names the version it read, so a
 * change made on disk meanwhile is never overwritten without the user choosing to: the
 * sheet then shows "changed on disk" with Reload and Keep mine. While open it follows the
 * file: when the page loads again after a change on disk, an untouched draft takes the new
 * text, an edited one shows the bar.
 */
export function ConfigEditor({ target, onClose }: { target: EditTarget; onClose: () => void }) {
  const { state, actions } = useStore();
  const [text, setText] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [original, setOriginal] = useState("");
  const [version, setVersion] = useState<string | null>(null);
  // The version on disk when it changed after the file was read and the draft has edits.
  const [onDisk, setOnDisk] = useState<FileText | { version: string | null } | null>(null);
  const [saving, setSaving] = useState(false);
  const draft = useRef({ text, original, version, saving, loaded });
  useEffect(() => {
    draft.current = { text, original, version, saving, loaded };
  });

  const adopt = (file: FileText) => {
    setText(file.text);
    setLoaded(true);
    setOriginal(file.text);
    setVersion(file.version);
    setOnDisk(null);
  };

  // The parent's close changes with each of its renders; reading again would drop the draft.
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    let live = true;
    void actions.readConfigFile(target.path).then((file) => {
      if (!live) return;
      if (file === null) close.current();
      else adopt(file);
    });
    return () => {
      live = false;
    };
  }, [actions, target.path]);

  // The page or the project's part loaded again after a change on disk; nothing to follow
  // before the file was read.
  const { configuration, projectConfiguration } = state.settings;
  useEffect(() => {
    const before = draft.current;
    if (!before.loaded || before.saving) return;
    let live = true;
    void actions.readConfigFile(target.path).then((file) => {
      const now = draft.current;
      if (!live || file === null || file.version === now.version) return;
      if (now.text === now.original || file.text === now.text) adopt(file);
      else setOnDisk(file);
    });
    return () => {
      live = false;
    };
  }, [actions, target.path, configuration, projectConfiguration]);

  const save = async () => {
    setSaving(true);
    const saved = await actions.writeConfigFile(target.path, text, version);
    setSaving(false);
    if (saved === null) return;
    if ("conflict" in saved) {
      setOnDisk({ version: saved.conflict });
      return;
    }
    actions.toast(`Saved ${target.title}`);
    onClose();
  };

  const reload = async () => {
    const file = await actions.readConfigFile(target.path);
    if (file !== null) adopt(file);
  };

  return (
    <Sheet
      title={target.title}
      full
      onClose={onClose}
      leading={
        <button className="done" onClick={onClose}>
          Cancel
        </button>
      }
      trailing={
        <button className="done cfg-save" disabled={!loaded || saving} onClick={() => void save()}>
          Save
        </button>
      }
      footer={<p className="note">{EDITOR_FOOTER}</p>}
    >
      <div className="cfg-ed">
        <p className="cfg-path">
          <span className="mono">{shortPath(target.path)}</span> · {target.note}
        </p>
        {onDisk !== null && (
          <div className="cfg-disk" role="status">
            <span className="dot s-wait" aria-hidden="true" />
            <span className="cfg-disk-t">This file changed on disk since you opened it.</span>
            <button className="b" onClick={() => void reload()}>
              Reload
            </button>
            <button
              className="b"
              onClick={() => {
                setVersion(onDisk.version);
                setOnDisk(null);
              }}
            >
              Keep mine
            </button>
          </div>
        )}
        <textarea
          className="cfg-text"
          aria-label={target.title}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          disabled={!loaded}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
      </div>
    </Sheet>
  );
}
