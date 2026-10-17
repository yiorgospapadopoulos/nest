import { useEffect, useEffectEvent, useState, type SyntheticEvent } from "react";
import type { Pixie, PixieSearchHit } from "../../api/types.ts";
import type { FileState } from "../../store/actions.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { Sheet } from "../../ui/Sheet.tsx";
import { AddHeading } from "./AddHeading.tsx";
import { FilePage } from "./FilePage.tsx";
import { factParts, isFact, today } from "./memory.ts";

interface Props {
  pixie: Pixie;
  onClose: () => void;
}

/** What the pixie remembers: the facts of MEMORY.md, its notes and a search over both. */
export function MemoryPage({ pixie, onClose }: Props) {
  const { actions } = useStore();
  const { id } = pixie;
  const [file, setFile] = useState<FileState | null>(null);
  // The new fact's field, open from Add until Escape.
  const [fact, setFact] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<PixieSearchHit[] | null>(null);
  const unreadable = useEffectEvent(onClose);

  useEffect(() => {
    void actions.readPixieFile(id, "memory").then((read) => {
      if (read === null) unreadable();
      else setFile(read);
    });
    void actions.pixieNotes(id).then(setNotes);
  }, [actions, id]);

  /** Saves MEMORY.md on the hash it was read with; true once saved. */
  const write = async (current: FileState, text: string): Promise<boolean> => {
    const result = await actions.savePixieFile(id, "memory", text, current.hash);
    if (result === null) return false;
    if ("stale" in result) {
      // The pixie wrote meanwhile: show its version and let the user do it again.
      setFile(result.stale);
      actions.toast("Memory changed meanwhile. Try again.", "info");
      return false;
    }
    setFile(result.saved);
    return true;
  };

  const add = async (event: SyntheticEvent, current: FileState, typed: string) => {
    event.preventDefault();
    const text = typed.trim();
    if (text === "") return;
    const base =
      current.text === "" || current.text.endsWith("\n") ? current.text : `${current.text}\n`;
    // Saved: the field stays open for the next one.
    if (await write(current, `${base}- ${today()}: ${text}\n`)) setFact("");
  };

  const search = async (event: SyntheticEvent) => {
    event.preventDefault();
    const q = query.trim();
    if (q !== "") setHits(await actions.searchPixie(id, q));
  };

  const lines = file?.text.split("\n") ?? [];
  const facts = lines.flatMap((line, index) => (isFact(line) ? [{ line, index }] : []));

  return (
    <Sheet title="Memory" full onClose={onClose}>
      {file === null ? (
        <h3 className="pxsub">Facts</h3>
      ) : (
        <AddHeading
          title="Facts"
          level={3}
          label="Add fact"
          onAdd={() => {
            setFact("");
          }}
        />
      )}
      {file !== null && (
        <>
          <div className="lgrp gl">
            {facts.length === 0 && <div className="srow hint">No facts yet</div>}
            {facts.map(({ line, index }) => {
              const { date, text } = factParts(line);
              return (
                <div key={index} className="srow pxfact">
                  <span className="pxdt">
                    <span>{text}</span>
                    <small>{date}</small>
                  </span>
                  <button
                    className="pxx"
                    aria-label={`Remove fact: ${text}`}
                    onClick={() => void write(file, lines.filter((_, j) => j !== index).join("\n"))}
                  >
                    <Icon name="x" />
                  </button>
                </div>
              );
            })}
          </div>
          {fact !== null && (
            <form className="pxform" onSubmit={(event) => void add(event, file, fact)}>
              <input
                className="pxin pxin-sm"
                aria-label="New fact"
                placeholder="New fact"
                value={fact}
                autoFocus
                onChange={(event) => {
                  setFact(event.target.value);
                }}
                onKeyDown={(event) => {
                  if (event.key !== "Escape") return;
                  // Not the page's Escape, which closes it.
                  event.stopPropagation();
                  setFact(null);
                }}
              />
              <button className="b b-pri pxgo" type="submit">
                Save
              </button>
            </form>
          )}
        </>
      )}

      <h3 className="pxsub">Notes</h3>
      {notes !== null && (
        <div className="lgrp gl">
          {notes.length === 0 && <div className="srow hint">No notes yet</div>}
          {notes.map((name) => (
            <button
              key={name}
              className="srow pxset"
              onClick={() => {
                setNote(name);
              }}
            >
              <span className="cn">
                <Icon name="file" />
                <span>{name}</span>
              </span>
              <Icon name="chevr" className="chv" />
            </button>
          ))}
        </div>
      )}

      <h3 className="pxsub">Search</h3>
      <form className="pxform" role="search" onSubmit={(event) => void search(event)}>
        <input
          className="pxin pxin-sm"
          type="search"
          aria-label="Search memory"
          placeholder="Search memory and notes"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
        />
      </form>
      {hits !== null && (
        <ul className="lgrp gl pxhits">
          {hits.length === 0 && <li className="srow hint">No matches</li>}
          {hits.map((hit, index) => (
            <li key={index} className="srow">
              {hit.file}: {hit.line}
            </li>
          ))}
        </ul>
      )}

      {note !== null && (
        <FilePage
          pixie={pixie}
          name={`notes/${note}`}
          title={note}
          onClose={() => {
            setNote(null);
          }}
        />
      )}
    </Sheet>
  );
}
