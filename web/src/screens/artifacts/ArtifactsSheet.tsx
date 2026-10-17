import { useEffect, useRef, useState } from "react";
import type { Artifact, ArtifactFilter } from "../../api/types.ts";
import { activityTime } from "../../format.ts";
import { artifactList, filterKey } from "../../store/artifacts.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { Sheet } from "../../ui/Sheet.tsx";
import { Confirm } from "../pixies/Confirm.tsx";
import { ArtifactReader, type LoadedVersion } from "./ArtifactReader.tsx";
import { saveFile } from "./files.ts";
import { KIND_ICONS, KIND_LABELS, originOf, type ArtifactScope, type Scopes } from "./view.ts";

interface Shown {
  id: string;
  version: number;
}

interface Props {
  // The switch's choices, the first shown first.
  scopes: Scopes;
  // Opens on this version, as a card in the transcript does.
  open?: Shown | undefined;
  onClose: () => void;
}

/** The artifact history (B79), newest first, and the reader of one of its versions. */
export function ArtifactsSheet({ scopes, open, onClose }: Props) {
  const { state, actions } = useStore();
  const [scope, setScope] = useState<ArtifactScope>(scopes[0]);
  const [reading, setReading] = useState<Shown | null>(open ?? null);
  const [confirm, setConfirm] = useState(false);
  // One deleted, here or on another device, leaves the reader.
  const shown = reading !== null && state.artifactsGone[reading.id] !== true ? reading : null;
  const artifact = shown === null ? undefined : state.artifacts[shown.id];
  const known = artifact !== undefined;
  const { loaded, retry } = useVersion(shown);
  const content = loaded?.content ?? null;
  const showsLatest = content !== null && content.version === artifact?.latest_version;
  const unseen = showsLatest && !artifact.seen;

  // Opened from a card before any list named it.
  useEffect(() => {
    if (shown !== null && !known) void actions.loadArtifact(shown.id);
  }, [actions, shown, known]);

  useEffect(() => {
    if (unseen) void actions.markArtifactSeen(content.artifact_id);
  }, [actions, unseen, content]);

  const copy = (text: string) => {
    navigator.clipboard.writeText(text).then(
      () => {
        actions.toast("Copied");
      },
      () => {
        actions.toast("Could not copy", "error");
      },
    );
  };

  return (
    <Sheet
      full
      title={shown === null ? "Artifacts" : (content?.title ?? artifact?.title ?? "Artifact")}
      onClose={onClose}
      leading={
        shown === null ? undefined : (
          <button
            className="done l afback"
            onClick={() => {
              setReading(null);
            }}
          >
            <Icon name="chevl" />
            Artifacts
          </button>
        )
      }
      footer={
        shown === null || content === null ? undefined : (
          <>
            <button
              className="b"
              onClick={() => {
                copy(content.content);
              }}
            >
              Copy
            </button>
            <button
              className="b"
              onClick={() => {
                saveFile(content.title, content.kind, content.content);
              }}
            >
              Save as file
            </button>
            <button
              className="b b-no"
              onClick={() => {
                setConfirm(true);
              }}
            >
              Delete
            </button>
          </>
        )
      }
    >
      {shown === null ? (
        <History
          scopes={scopes}
          scope={scope}
          onScope={setScope}
          onOpen={(found) => {
            setReading({ id: found.id, version: found.latest_version });
          }}
        />
      ) : (
        <ArtifactReader
          artifact={artifact}
          version={shown.version}
          loaded={loaded}
          onStep={(version) => {
            setReading({ id: shown.id, version });
          }}
          onRetry={retry}
        />
      )}
      {confirm && shown !== null && (
        <Confirm
          title="Delete this artifact?"
          about="Every version of it goes. This cannot be undone."
          action="Delete"
          onConfirm={() => void actions.deleteArtifact(shown.id)}
          onClose={() => {
            setConfirm(false);
          }}
        />
      )}
    </Sheet>
  );
}

/** The version shown, read once per version; `retry` reads it again after a failure. */
function useVersion(shown: Shown | null): { loaded: LoadedVersion | undefined; retry: () => void } {
  const { actions } = useStore();
  const [read, setRead] = useState<(LoadedVersion & { key: string }) | null>(null);
  const [tries, setTries] = useState(0);
  const id = shown?.id;
  const version = shown?.version;
  const key = `${String(id)}:${String(version)}:${String(tries)}`;
  useEffect(() => {
    if (id === undefined || version === undefined) return;
    let current = true;
    void actions.artifactVersion(id, version).then((content) => {
      if (current) setRead({ key, content });
    });
    return () => {
      current = false;
    };
  }, [actions, id, version, key]);
  return {
    loaded: read?.key === key ? read : undefined,
    retry: () => {
      setTries((n) => n + 1);
    },
  };
}

interface HistoryProps {
  scopes: ArtifactScope[];
  scope: ArtifactScope;
  onScope: (scope: ArtifactScope) => void;
  onOpen: (artifact: Artifact) => void;
}

function History({ scopes, scope, onScope, onOpen }: HistoryProps) {
  const { state, actions } = useStore();
  const filter = scope.filter;
  const key = filterKey(filter);
  const [failed, setFailed] = useState<string | null>(null);
  const [tries, setTries] = useState(0);
  // The filter as given, while its key says when to load: the scopes are new each render.
  const latest = useRef<ArtifactFilter>(filter);
  useEffect(() => {
    latest.current = filter;
  });
  useEffect(() => {
    let current = true;
    void actions.loadArtifacts(latest.current).then((done) => {
      if (current) setFailed(done ? null : key);
    });
    return () => {
      current = false;
    };
  }, [actions, key, tries]);
  const artifacts = artifactList(state, filter);
  const every = Object.keys(filter).length === 0;
  const now = new Date();
  return (
    <>
      {scopes.length > 1 && (
        <div className="afsw mseg" role="group" aria-label="Show artifacts of">
          {scopes.map((each) => (
            <button
              key={each.label}
              aria-pressed={filterKey(each.filter) === key}
              onClick={() => {
                onScope(each);
              }}
            >
              {each.label}
            </button>
          ))}
        </div>
      )}
      {artifacts === null && failed !== key && <p className="note">Loading...</p>}
      {artifacts === null && failed === key && (
        <div className="note">
          The artifacts could not be loaded.{" "}
          <button
            className="lnk"
            onClick={() => {
              setTries((n) => n + 1);
            }}
          >
            Retry
          </button>
        </div>
      )}
      {artifacts?.length === 0 && (
        <div className="tx-empty afempty">
          <Icon name="doc" />
          <b>No artifacts yet</b>
          <span>Reports, plans and comparisons an agent saves show here.</span>
        </div>
      )}
      {artifacts !== null && artifacts.length > 0 && (
        <ul className="afl" aria-label="Artifacts">
          {artifacts.map((artifact) => (
            <li key={artifact.id}>
              <button
                className="afr"
                onClick={() => {
                  onOpen(artifact);
                }}
              >
                <span className="afi">
                  <Icon name={KIND_ICONS[artifact.kind]} />
                </span>
                <span className="afm">
                  <b>{artifact.title}</b>
                  <span>
                    {[
                      KIND_LABELS[artifact.kind],
                      every && artifact.pixie_id === null ? artifact.repo : null,
                      originOf(artifact),
                      activityTime(artifact.updated_at, now),
                    ]
                      .filter((part) => part !== null)
                      .join(" · ")}
                  </span>
                </span>
                {!artifact.seen && <span className="afn" role="img" aria-label="New" />}
                <Icon name="chevr" className="cv" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
