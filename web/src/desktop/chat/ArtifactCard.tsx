import { use, useEffect } from "react";
import { KIND_ICONS, KIND_LABELS } from "../../screens/artifacts/view.ts";
import { useStore } from "../../store/context.ts";
import type { ArtifactItem } from "../../transcript/build.ts";
import { Icon } from "../../ui/Icon.tsx";
import { openArtifact } from "../artifacts/viewState.ts";
import { ShellContext } from "../shell/context.ts";
import { Button } from "../ui/controls.tsx";
import { useRows } from "./rowsContext.ts";

/**
 * A chat saved an artifact (B79), as the Mac's ArtifactCardView: its kind, title and
 * "Saved" or "Version 3", and Open, which shows that version in the Artifacts view. Once the artifact is
 * deleted the card says so and Open is off.
 */
export function ArtifactCard({ item, ev }: { item: ArtifactItem; ev: string }) {
  const { state, actions } = useStore();
  const shell = use(ShellContext);
  const { chat, host } = useRows();
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
      className="dc-card dc-art"
      role="group"
      aria-label={`Artifact: ${item.title}`}
      data-ev={ev}
    >
      <Icon name={KIND_ICONS[item.artifactKind]} className="dc-arti" />
      <div className="dc-cardb">
        <span className={gone ? "dc-cardt gone" : "dc-cardt"}>{item.title}</span>
        <span className="dc-cardm">
          {KIND_LABELS[item.artifactKind]} · {status}
        </span>
      </div>
      <Button
        disabled={gone || (shell === null && host === null)}
        title={gone ? "This artifact was deleted" : `Open ${item.title} in Artifacts`}
        // That version in the Artifacts view, this chat focused, as the Mac's openArtifact.
        onClick={() => {
          if (host !== null) host.openArtifact(id, item.version);
          else if (shell !== null)
            openArtifact(shell, id, item.version, chat === "" ? undefined : chat);
        }}
      >
        Open
      </Button>
    </div>
  );
}
