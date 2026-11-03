import { useEffect, useEffectEvent, useState } from "react";
import type { Pixie } from "../../api/types.ts";
import type { FileState } from "../../store/actions.ts";
import { useStore } from "../../store/context.ts";
import { Button } from "../ui/controls.tsx";
import { StatusDot } from "./bits.tsx";
import { PanelPageHeader } from "./parts.tsx";

interface Props {
  pixie: Pixie;
  // "soul" or "notes/<name>".
  name: string;
  title: string;
  back: string;
  close: () => void;
}

/**
 * A file of the pixie's folder as plain text, inside the details panel (PixieFilePage.swift).
 * Saving names the hash it read, so a change the pixie made meanwhile is never overwritten
 * without the user choosing to (D072).
 */
export function FilePage({ pixie, name, title, back, close }: Props) {
  const { actions } = useStore();
  // As read; null while loading.
  const [file, setFile] = useState<FileState | null>(null);
  const [text, setText] = useState("");
  // The file as it is now, after a save that named an old hash.
  const [stale, setStale] = useState<FileState | null>(null);
  const [saving, setSaving] = useState(false);
  const unreadable = useEffectEvent(close);

  useEffect(() => {
    let current = true;
    void actions.readPixieFile(pixie.id, name).then((loaded) => {
      if (!current) return;
      if (loaded === null) {
        unreadable();
        return;
      }
      setFile(loaded);
      setText(loaded.text);
    });
    return () => {
      current = false;
    };
  }, [actions, pixie.id, name]);

  const save = (hash: string | null) => {
    setStale(null);
    setSaving(true);
    void actions.savePixieFile(pixie.id, name, text, hash).then((result) => {
      setSaving(false);
      if (result === null) return;
      if ("stale" in result) {
        setStale(result.stale);
        return;
      }
      actions.toast(`Saved ${title}`);
      close();
    });
  };

  return (
    <div className="pd-page">
      <PanelPageHeader title={title} back={back} onBack={close}>
        <Button
          kind="primary"
          disabled={file === null || saving}
          onClick={() => {
            save(file?.hash ?? null);
          }}
        >
          Save
        </Button>
      </PanelPageHeader>
      {stale !== null && (
        <div className="pd-stale">
          <span className="pd-stale-h">
            <StatusDot tone="wait" />
            Changed meanwhile
          </span>
          <p>The file changed after you opened it, perhaps by {pixie.name}.</p>
          <div className="pd-stale-b">
            <Button
              onClick={() => {
                setFile(stale);
                setText(stale.text);
                setStale(null);
              }}
            >
              Reload
            </Button>
            <Button
              kind="primary"
              onClick={() => {
                save(stale.hash);
              }}
            >
              Keep mine
            </Button>
          </div>
        </div>
      )}
      <textarea
        className="pd-editor"
        aria-label={title}
        spellCheck={false}
        disabled={file === null}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key === "s" && (event.ctrlKey || event.metaKey) && file !== null && !saving) {
            event.preventDefault();
            save(file.hash);
          }
        }}
      />
    </div>
  );
}
