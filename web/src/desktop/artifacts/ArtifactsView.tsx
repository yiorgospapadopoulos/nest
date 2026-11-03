import { useEffect, useRef, useState } from "react";
import type { Artifact } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { useShell } from "../shell/context.ts";
import { Button } from "../ui/controls.tsx";
import { ArtifactReader } from "./ArtifactReader.tsx";
import { Glyph, KindGlyph } from "./glyphs.tsx";
import {
  artifactScope,
  emptyText,
  filterOf,
  keptSelection,
  listed,
  queryKey,
  queryLabel,
  type ArtifactQuery,
  type ArtifactScope,
} from "./query.ts";
import { origin, when } from "./text.ts";
import { useNow } from "../pixies/useNow.ts";
import { select, setWide, showScope, useArtifactsView } from "./viewState.ts";
import "./artifacts.css";

/**
 * The Artifacts view (B79), as the Mac's ArtifactsView: the history on the left, newest
 * first, the focused chat's or pixie's with a switch to the wider list, and the selected
 * one in the reader. `repo` is null in the Pixies tab.
 */
export function ArtifactsView({ repo }: { repo: string | null }) {
  const { state, actions } = useStore();
  const shell = useShell();
  const view = useArtifactsView();
  const scope = artifactScope({
    project: repo,
    focused: shell.state.layout.focused,
    sessions: state.sessions,
    pixies: state.pixies,
  });
  const key = `${scope.narrow === null ? "" : queryKey(scope.narrow)}|${queryKey(scope.wide)}`;
  // A new scope starts on its narrow list.
  const wide = view.scope === key && view.wide;
  const query = wide || scope.narrow === null ? scope.wide : scope.narrow;
  const list = listed(state, query);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    showScope(key);
  }, [key]);

  // The query as given, while its key says when to load: it is new each render.
  const shownKey = queryKey(query);
  const latest = useRef(query);
  useEffect(() => {
    latest.current = query;
  });
  useEffect(() => {
    let current = true;
    void actions.loadArtifacts(filterOf(latest.current)).then((done) => {
      if (current) setFailed(done ? null : shownKey);
    });
    return () => {
      current = false;
    };
  }, [actions, shownKey]);

  // A selection the list lacks, or none, moves to its newest; one deleted leaves too.
  const kept = list === null ? view.selection : keptSelection(list, view.selection);
  useEffect(() => {
    if (list !== null) select(kept);
  }, [list, kept]);

  const selected = kept === null ? undefined : state.artifacts[kept.id];
  useEffect(() => {
    if (kept !== null && selected === undefined && state.artifactsGone[kept.id] !== true) {
      void actions.loadArtifact(kept.id);
    }
  }, [actions, kept, selected, state.artifactsGone]);

  return (
    <div className="da-view">
      <ArtifactList
        scope={scope}
        wide={wide}
        query={query}
        list={list}
        failed={failed === shownKey}
        selected={kept?.id ?? null}
        onWide={(next) => {
          showScope(key);
          setWide(next);
        }}
      />
      <div className="da-sep" />
      {selected !== undefined && kept !== null ? (
        <ArtifactReader
          key={selected.id}
          artifact={selected}
          version={Math.min(Math.max(kept.version, 1), selected.latest_version)}
        />
      ) : (
        <div className="da-none">
          <Glyph name="richtext" />
          <span>Select an artifact to read it</span>
        </div>
      )}
    </div>
  );
}

interface ListProps {
  scope: ArtifactScope;
  wide: boolean;
  query: ArtifactQuery;
  list: Artifact[] | null;
  failed: boolean;
  selected: string | null;
  onWide: (wide: boolean) => void;
}

/** The scope switch over the history rows. */
function ArtifactList({ scope, wide, query, list, failed, selected, onWide }: ListProps) {
  const now = useNow(30_000);
  const narrow = scope.narrow;
  return (
    <div className="da-list">
      <div className="da-lhead">
        {narrow !== null ? (
          <span className="da-scopes" role="group" aria-label="Show artifacts of">
            {[false, true].map((each) => (
              <button
                key={String(each)}
                type="button"
                className="da-scope"
                aria-pressed={each === wide}
                onClick={() => {
                  onWide(each);
                }}
              >
                {queryLabel(each ? scope.wide : narrow)}
              </button>
            ))}
          </span>
        ) : (
          <span className="da-label">{queryLabel(scope.wide)}</span>
        )}
        {list !== null && <span className="da-count">{list.length}</span>}
      </div>
      <div className="da-rows">
        {failed ? (
          <p className="da-lfail">Could not load the artifacts</p>
        ) : (
          list?.length === 0 && (
            <div className="da-empty">
              <p>{emptyText(query)}</p>
              <span>A chat saves a report, plan or page here when you ask it for one.</span>
              {narrow !== null && !wide && (
                <Button
                  onClick={() => {
                    onWide(true);
                  }}
                >
                  Show {queryLabel(scope.wide).toLowerCase()}
                </Button>
              )}
            </div>
          )
        )}
        {list !== null && list.length > 0 && (
          <div role="list" aria-label="Artifacts">
            {list.map((artifact) => (
              <div key={artifact.id} role="listitem">
                <ArtifactRow artifact={artifact} selected={artifact.id === selected} now={now} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * An artifact in the history: its kind, title, the chat or pixie that made it and when;
 * a dot while its latest version is not opened yet.
 */
function ArtifactRow({
  artifact,
  selected,
  now,
}: {
  artifact: Artifact;
  selected: boolean;
  now: Date;
}) {
  return (
    <button
      type="button"
      className="da-row"
      aria-current={selected || undefined}
      onClick={() => {
        select({ id: artifact.id, version: artifact.latest_version });
      }}
    >
      <KindGlyph kind={artifact.kind} className="da-rkind" />
      <span className="da-rtext">
        <span className={artifact.seen ? "da-rt" : "da-rt new"}>{artifact.title}</span>
        <span className="da-rm">
          {origin(artifact)} · {when(artifact.updated_at, now)}
        </span>
      </span>
      {!artifact.seen && <span className="da-dot" role="img" aria-label="Not opened" />}
    </button>
  );
}
