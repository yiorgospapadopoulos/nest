import { useState } from "react";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ArtifactsSheet } from "./ArtifactsSheet.tsx";
import type { Scopes } from "./view.ts";

/** The header button to the artifact history, with how many are new in every project. */
export function ArtifactsButton({ scopes }: { scopes: Scopes }) {
  const { state } = useStore();
  const [open, setOpen] = useState(false);
  const unseen = state.unseenArtifacts;
  return (
    <>
      <button
        className="ib"
        aria-haspopup="dialog"
        aria-label={unseen > 0 ? `Artifacts, ${String(unseen)} new` : "Artifacts"}
        onClick={() => {
          setOpen(true);
        }}
      >
        <Icon name="doc" />
        {unseen > 0 && <span className="cnt">{unseen}</span>}
      </button>
      {open && (
        <ArtifactsSheet
          scopes={scopes}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </>
  );
}
