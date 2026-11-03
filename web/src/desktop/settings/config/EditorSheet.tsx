import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { EDITOR_FOOTER } from "../../../screens/settings/configText.ts";
import { useStore } from "../../../store/context.ts";
import { useApi } from "../../context.ts";
import { SheetFrame } from "../../sheets/SheetFrame.tsx";
import { Button } from "../../ui/controls.tsx";
import { FileEditor } from "./fileEditor.ts";
import type { EditTarget } from "./modals.ts";
import { fileName, shortPath, useOpenPath, useSettingsChange } from "./util.ts";

/**
 * A configuration file in place, as the Mac's ConfigEditorSheet: its name and path, the
 * "changed on disk" bar, the text in mono, and Save. While open it follows the file: when
 * the page reads the engines' files again after a change on disk, it checks this one.
 */
export function EditorSheet({ target, onClose }: { target: EditTarget; onClose: () => void }) {
  const api = useApi();
  const { state, actions } = useStore();
  const change = useSettingsChange();
  const openPath = useOpenPath();
  const [editor] = useState(() => new FileEditor(api, target.path));
  const draft = useSyncExternalStore(editor.subscribe, () => editor.state);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });

  useEffect(() => {
    editor.load().catch((error: unknown) => {
      const why = error instanceof Error ? error.message : String(error);
      actions.toast(`Could not read ${target.title}: ${why}`, "error");
      close.current();
    });
  }, [editor, actions, target.title]);

  // The page or a project's part was read again after a change on disk.
  const { configuration, projectConfiguration } = state.settings;
  useEffect(() => {
    void editor.checkDisk().catch(() => undefined);
  }, [editor, configuration, projectConfiguration]);

  const save = () => {
    change(`Could not save ${target.title}`, async () => {
      if (await editor.save()) {
        actions.toast(`Saved ${target.title}`);
        onClose();
      }
    });
  };

  return (
    <SheetFrame
      title={target.title}
      width={800}
      maxHeight={660}
      onClose={onClose}
      footer={
        <>
          {draft.error === null ? (
            <span className="dkc-ed-foot">{EDITOR_FOOTER}</span>
          ) : (
            <span className="dkc-ed-foot bad">{draft.error}</span>
          )}
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" disabled={!draft.loaded || draft.saving} onClick={save}>
            Save
          </Button>
        </>
      }
    >
      <p className="dkc-ed-path">
        <span className="mono">{fileName(target.path)}</span>
        <span className="mono">{shortPath(target.path)}</span>
        {target.note !== null && <span>· {target.note}</span>}
        {openPath !== null && draft.loaded && (
          <Button
            kind="plain"
            onClick={() => {
              openPath(target.path, true);
            }}
          >
            Show in Files
          </Button>
        )}
      </p>
      {draft.onDisk !== null && (
        <div className="dkc-disk" role="status">
          <i aria-hidden="true" />
          <span>This file changed on disk since you opened it.</span>
          <Button
            onClick={() => {
              editor.reload();
            }}
          >
            Reload
          </Button>
          <Button
            onClick={() => {
              editor.keepMine();
            }}
          >
            Keep mine
          </Button>
        </div>
      )}
      <textarea
        className="dkc-ed-text"
        aria-label={target.title}
        spellCheck={false}
        autoComplete="off"
        data-autofocus
        disabled={!draft.loaded}
        value={draft.text}
        onChange={(event) => {
          editor.setText(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key === "s" && event.ctrlKey && !event.altKey && !event.shiftKey) {
            event.preventDefault();
            if (draft.loaded && !draft.saving) save();
          }
        }}
      />
    </SheetFrame>
  );
}
