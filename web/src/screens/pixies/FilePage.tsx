import { useEffect, useEffectEvent, useState } from "react";
import type { Pixie } from "../../api/types.ts";
import type { FileState } from "../../store/actions.ts";
import { useStore } from "../../store/context.ts";
import { Sheet } from "../../ui/Sheet.tsx";

interface Props {
  pixie: Pixie;
  // soul, memory or notes/<name>.
  name: string;
  title: string;
  onClose: () => void;
}

/**
 * One of the pixie's files as plain text. Saving names the hash it read, so a change the
 * pixie made meanwhile is never overwritten without the user choosing to (D057).
 */
export function FilePage({ pixie, name, title, onClose }: Props) {
  const { actions } = useStore();
  // As read; null while loading.
  const [file, setFile] = useState<FileState | null>(null);
  const [text, setText] = useState("");
  // The file as it is now, after a save that named an old hash.
  const [stale, setStale] = useState<FileState | null>(null);
  const [saving, setSaving] = useState(false);
  const unreadable = useEffectEvent(onClose);

  useEffect(() => {
    void actions.readPixieFile(pixie.id, name).then((loaded) => {
      if (loaded === null) {
        unreadable();
        return;
      }
      setFile(loaded);
      setText(loaded.text);
    });
  }, [actions, pixie.id, name]);

  // The hash a save names: the one read, or the one the user chose to save over.
  const read = file === null ? null : file.hash;

  const save = async (hash: string | null) => {
    setStale(null);
    setSaving(true);
    const result = await actions.savePixieFile(pixie.id, name, text, hash);
    setSaving(false);
    if (result === null) return;
    if ("stale" in result) setStale(result.stale);
    else onClose();
  };

  return (
    <Sheet
      title={title}
      full
      onClose={onClose}
      leading={
        <button className="done l" onClick={onClose}>
          Close
        </button>
      }
      trailing={
        <button className="done" disabled={file === null || saving} onClick={() => void save(read)}>
          Save
        </button>
      }
    >
      {stale !== null && (
        <div className="pxstale" role="alert">
          <b>Changed meanwhile</b>
          <span>The file changed after you opened it, perhaps by {pixie.name}.</span>
          <div className="acts">
            <button
              className="b"
              onClick={() => {
                setFile(stale);
                setText(stale.text);
                setStale(null);
              }}
            >
              Reload
            </button>
            <button className="b b-pri" onClick={() => void save(stale.hash)}>
              Keep mine
            </button>
          </div>
        </div>
      )}
      <textarea
        className="pxfile"
        aria-label={title}
        value={text}
        disabled={file === null}
        onChange={(event) => {
          setText(event.target.value);
        }}
      />
    </Sheet>
  );
}
