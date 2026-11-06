// The header of the small map and of the full tree: Find, Reload and what follows them, then
// any remote that failed (B131).
import type { ReactNode } from "react";
import type { Reload } from "../../chat/branchMaps.ts";
import { Glyph } from "../../chat/glyphs.tsx";

export function FindField({
  value,
  placeholder,
  onChange,
}: {
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="fr-bmfind">
      <Glyph name="search" size={11} />
      <input
        value={value}
        placeholder={placeholder}
        aria-label={placeholder}
        spellCheck={false}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      />
    </label>
  );
}

export function MapBar({
  query,
  onQuery,
  reload,
  children,
}: {
  query: string;
  onQuery: (query: string) => void;
  reload: Reload;
  children?: ReactNode;
}) {
  return (
    <>
      <div className="fr-bmbar">
        <FindField value={query} placeholder="Find a branch" onChange={onQuery} />
        <button
          className={reload.running ? "fr-bmib run" : "fr-bmib"}
          title="Reload"
          aria-label="Reload"
          aria-busy={reload.running}
          onClick={reload.start}
        >
          <Glyph name="refresh" size={13} />
        </button>
        {children}
        {reload.running && (
          <span className="fr-bmprog">
            <i />
          </span>
        )}
      </div>
      {reload.failures.map((failure) => (
        <div className="fr-bmnote" key={failure.remotes}>
          <div>
            <b>{failure.remotes}</b> {failure.reason}
          </div>
          <button className="fr-bmib small" aria-label="Dismiss" onClick={reload.dismiss}>
            <Glyph name="close" size={11} />
          </button>
        </div>
      ))}
    </>
  );
}
