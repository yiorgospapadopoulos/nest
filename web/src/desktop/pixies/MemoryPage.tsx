import { useEffect, useEffectEvent, useRef, useState } from "react";
import type { Pixie, PixieSearchHit } from "../../api/types.ts";
import type { FileState } from "../../store/actions.ts";
import { useStore } from "../../store/context.ts";
import { PxGlyph } from "./glyphs.tsx";
import type { PixiePage } from "./panel.ts";
import {
  DetailHeading,
  DetailLine,
  HeadingAddButton,
  Page,
  PanelPageHeader,
  RemoveButton,
} from "./parts.tsx";
import { addingFact, factDay, facts, removingLine } from "./words.ts";

/**
 * What the pixie remembers (PixieMemoryPage.swift): the facts of MEMORY.md, its notes and
 * a search over both, inside the details panel.
 */
export function MemoryPage({ pixie, open }: { pixie: Pixie; open: (page: PixiePage) => void }) {
  const { actions } = useStore();
  const [file, setFile] = useState<FileState | null>(null);
  const [fact, setFact] = useState("");
  // The Add fact field shows, from Add at the right of Facts.
  const [adding, setAdding] = useState(false);
  const factField = useRef<HTMLInputElement>(null);
  const [notes, setNotes] = useState<string[] | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<PixieSearchHit[] | null>(null);
  const unreadable = useEffectEvent(() => {
    open({ page: "details" });
  });

  useEffect(() => {
    let current = true;
    void actions
      .readPixieFile(pixie.id, "memory")
      .then((read) => {
        if (!current) return null;
        if (read === null) {
          unreadable();
          return null;
        }
        setFile(read);
        return actions.pixieNotes(pixie.id);
      })
      .then((listed) => {
        if (current && listed !== null) setNotes(listed);
      });
    return () => {
      current = false;
    };
  }, [actions, pixie.id]);

  useEffect(() => {
    if (adding) factField.current?.focus();
  }, [adding]);

  // Saves MEMORY.md on the hash it was read with. When the pixie wrote meanwhile, its
  // version shows and the user does it again.
  const write = (text: string, over: FileState, then?: () => void) => {
    void actions.savePixieFile(pixie.id, "memory", text, over.hash).then((result) => {
      if (result === null) return;
      if ("stale" in result) {
        setFile(result.stale);
        actions.toast("Memory changed meanwhile. Try again.", "info");
        return;
      }
      setFile(result.saved);
      then?.();
    });
  };

  const add = (over: FileState) => {
    const text = fact.trim();
    if (text === "") return;
    write(addingFact(text, over.text, factDay(new Date())), over, () => {
      setFact("");
      factField.current?.focus();
    });
  };

  const search = () => {
    const text = query.trim();
    if (text === "") return;
    void actions.searchPixie(pixie.id, text).then(setHits);
  };

  const shown = file === null ? [] : facts(file.text);

  return (
    <Page
      header={
        <PanelPageHeader
          title="Memory"
          back="Details"
          onBack={() => {
            open({ page: "details" });
          }}
        />
      }
    >
      <DetailHeading title="Facts" divided={false}>
        {file !== null && (
          <HeadingAddButton
            label="Add fact"
            onClick={() => {
              setAdding(true);
              factField.current?.focus();
            }}
          />
        )}
      </DetailHeading>
      {file !== null && (
        <>
          {adding && (
            <input
              ref={factField}
              className="pd-field pd-addfact"
              aria-label="Add fact"
              placeholder="New fact, Return to add"
              value={fact}
              onChange={(event) => {
                setFact(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  add(file);
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  event.stopPropagation();
                  setFact("");
                  setAdding(false);
                }
              }}
            />
          )}
          {shown.length === 0 && <DetailLine text="No facts yet" dim />}
          {shown.map((each) => (
            <div key={each.line} className="pd-fact">
              <span className="pd-fact-t">
                <span className="pd-select">{each.text}</span>
                {each.date !== "" && <small>{each.date}</small>}
              </span>
              <RemoveButton
                label={`Remove fact: ${each.text}`}
                onClick={() => {
                  write(removingLine(each.line, file.text), file);
                }}
              />
            </div>
          ))}
        </>
      )}

      <DetailHeading title="Notes" />
      {notes !== null && (
        <>
          {notes.length === 0 && <DetailLine text="No notes yet" dim />}
          {notes.map((note) => (
            <button
              key={note}
              className="pd-noterow"
              aria-label={`Note ${note}`}
              onClick={() => {
                open({ page: "note", note });
              }}
            >
              <PxGlyph name="file" className="pd-noteicon" />
              <span>{note}</span>
              <PxGlyph name="chevronRight" className="pd-chev" />
            </button>
          ))}
        </>
      )}

      <DetailHeading title="Search" />
      <input
        className="pd-field pd-search"
        aria-label="Search memory"
        placeholder="Search memory and notes"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            search();
          }
        }}
      />
      {hits !== null && (
        <div className="pd-hits">
          {hits.length === 0 && <DetailLine text="No matches" dim />}
          {hits.map((hit, index) => (
            <p key={index} className="pd-hit pd-select">
              {hit.file}: {hit.line}
            </p>
          ))}
        </div>
      )}
    </Page>
  );
}
