import { useEffect, useState } from "react";
import type { ArtifactItem } from "../../transcript/build.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ArtifactsSheet } from "./ArtifactsSheet.tsx";
import { KIND_ICONS, KIND_LABELS, type Scopes } from "./view.ts";

interface Props {
  item: ArtifactItem;
  ev: string;
  // The history the reader goes back to.
  scopes: Scopes;
}

/**
 * An artifact the chat saved (B79): the version it names opens in the reader, also once
 * newer ones exist. One deleted since shows so, with nothing to open.
 */
export function ArtifactCard({ item, ev, scopes }: Props) {
  const { state, actions } = useStore();
  const [open, setOpen] = useState(false);
  const { artifactId: id } = item;
  const gone = state.artifactsGone[id] === true;
  const known = id in state.artifacts;

  useEffect(() => {
    if (!known && !gone) void actions.loadArtifact(id);
  }, [actions, id, known, gone]);

  const status = gone
    ? "Deleted"
    : item.action === "created"
      ? "Saved"
      : `Version ${String(item.version)}`;
  return (
    <div
      className={gone ? "pxcard afcard gone" : "pxcard afcard"}
      role="group"
      aria-label={`Artifact: ${item.title}`}
      data-ev={ev}
    >
      <span className="afi">
        <Icon name={KIND_ICONS[item.artifactKind]} />
      </span>
      <div className="pxcb">
        <b>{item.title}</b>
        <span className="pxcm">
          {status} · {KIND_LABELS[item.artifactKind]}
        </span>
      </div>
      <div className="pxca">
        <button
          className="b qb2"
          disabled={gone}
          onClick={() => {
            setOpen(true);
          }}
        >
          Open
        </button>
      </div>
      {open && !gone && (
        <ArtifactsSheet
          scopes={scopes}
          open={{ id, version: item.version }}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </div>
  );
}
