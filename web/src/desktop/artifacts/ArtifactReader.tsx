import { useEffect, useRef, useState } from "react";
import type { Artifact, ArtifactContent } from "../../api/types.ts";
import { PRINT } from "../../screens/artifacts/bridge.ts";
import { download } from "../../screens/artifacts/files.ts";
import { useStore } from "../../store/context.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import type { Bridge } from "../bridge.ts";
import { useBridge } from "../context.ts";
import { Button } from "../ui/controls.tsx";
import { ArtifactFrame } from "./ArtifactFrame.tsx";
import { ConfirmDialog } from "./ConfirmDialog.tsx";
import { Glyph } from "./glyphs.tsx";
import { useAsks, useStoredSize } from "./pageData.ts";
import { ASKING, exportsPdf, fileName, line, pdfName, savedText, versionText } from "./text.ts";
import { useNow } from "../pixies/useNow.ts";
import { select } from "./viewState.ts";

interface Props {
  artifact: Artifact;
  // Its version within 1 and the latest.
  version: number;
}

/**
 * The selected version (ArtifactsView.swift's ArtifactReader): its title, kind, where it
 * came from and when (or that the user edited it), the version stepper, Export PDF for
 * slides and documents, Copy, Save as file, Clear page data once the page stored any, and
 * Delete, then the document.
 */
export function ArtifactReader({ artifact, version }: Props) {
  const { actions } = useStore();
  const bridge = useBridge();
  const now = useNow(30_000);
  const frame = useRef<HTMLIFrameElement>(null);
  const { content, failed, retry } = useVersion(artifact.id, version);
  const { size, setSize, reread } = useStoredSize(artifact.id);
  const asks = useAsks(artifact.id);
  const [confirming, setConfirming] = useState<"delete" | "clear" | null>(null);
  const latest = artifact.latest_version;
  const shown = content?.version === version ? content : null;
  const title = shown?.title ?? artifact.title;
  const unseen = shown !== null && version === latest && !artifact.seen;

  useEffect(() => {
    if (unseen) void actions.markArtifactSeen(artifact.id);
  }, [actions, unseen, artifact.id]);

  const step = (offset: number) => {
    select({ id: artifact.id, version: version + offset });
  };
  const stepButton = (offset: number, label: string) => (
    <Button
      kind="plain"
      iconOnly
      aria-label={label}
      title={label}
      disabled={version + offset < 1 || version + offset > latest}
      onClick={() => {
        step(offset);
      }}
    >
      <Glyph name={offset < 0 ? "chevronLeft" : "chevronRight"} className="da-step" />
    </Button>
  );

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
    <section className="da-reader" aria-label={title}>
      <header className="da-rhead">
        <div className="da-rtitle">
          <h2>{title}</h2>
          <p>
            {line(
              artifact,
              shown?.author ?? "agent",
              shown?.created_at ?? artifact.updated_at,
              now,
              size,
              asks.count,
            )}
          </p>
        </div>
        {asks.asking && (
          <span className="da-asking" role="status">
            <Fireflies size={10} />
            {ASKING}
          </span>
        )}
        {latest > 1 && (
          <span className="da-versions" role="group" aria-label="Versions">
            {stepButton(-1, "Previous version")}
            <span>{versionText(version, latest)}</span>
            {stepButton(1, "Next version")}
          </span>
        )}
        {exportsPdf(artifact.kind) && (
          <Button
            disabled={shown === null}
            title={pdfName(title)}
            onClick={() => {
              frame.current?.contentWindow?.postMessage(PRINT, "*");
            }}
          >
            <Glyph name="richtext" />
            Export PDF…
          </Button>
        )}
        <Button
          disabled={shown === null}
          title="Copy this version's text"
          onClick={() => {
            if (shown !== null) copy(shown.content);
          }}
        >
          <Glyph name="copy" />
          Copy
        </Button>
        <Button
          disabled={shown === null}
          title={fileName(title, artifact.kind)}
          onClick={() => {
            if (shown === null) return;
            saveAs(shown, bridge).then(
              (saved) => {
                if (saved !== null) actions.toast(`Saved ${saved.split("/").at(-1) ?? saved}`);
              },
              (error: unknown) => {
                const why = error instanceof Error ? error.message : String(error);
                actions.toast(`Could not save the file: ${why}`, "error");
              },
            );
          }}
        >
          <Glyph name="save" />
          Save as file
        </Button>
        {size > 0 && (
          <Button
            kind="plain"
            iconOnly
            aria-label="Clear page data"
            title="Clear page data"
            onClick={() => {
              setConfirming("clear");
            }}
          >
            <Glyph name="eraser" />
          </Button>
        )}
        <Button
          kind="plain"
          iconOnly
          aria-label="Delete"
          title="Delete this artifact"
          onClick={() => {
            setConfirming("delete");
          }}
        >
          <Glyph name="trash" />
        </Button>
      </header>
      <div className="da-doc">
        {shown !== null ? (
          // Another version is another page: its own bridge, and no question left open.
          <ArtifactFrame
            key={`${shown.artifact_id}:${String(shown.version)}`}
            frame={frame}
            content={shown}
            editable={shown.kind === "document" && shown.version === latest}
            onSaved={(saved) => {
              select({ id: artifact.id, version: saved });
            }}
            onStored={setSize}
            onChangedElsewhere={reread}
            onAsk={asks.local}
          />
        ) : failed ? (
          <p className="da-failed">
            This version could not be loaded.{" "}
            <Button kind="link" onClick={retry}>
              Retry
            </Button>
          </p>
        ) : (
          <Fireflies size={14} />
        )}
      </div>
      {confirming === "delete" && (
        <ConfirmDialog
          title={`Delete “${artifact.title}”?`}
          message="Every version is removed. Its cards in chats show it as deleted."
          action="Delete"
          destructive
          onConfirm={() => void actions.deleteArtifact(artifact.id)}
          onClose={() => {
            setConfirming(null);
          }}
        />
      )}
      {confirming === "clear" && (
        <ConfirmDialog
          title="Clear this page’s data?"
          message="What the page stored is removed for every version and on every device. Open pages are told."
          action="Clear page data"
          destructive
          onConfirm={() => {
            actions.clearArtifactStorage(artifact.id).then(
              () => {
                setSize(0);
              },
              () => {
                actions.toast("Could not clear the page data", "error");
              },
            );
          }}
          onClose={() => {
            setConfirming(null);
          }}
        />
      )}
    </section>
  );
}

/**
 * Save as file: the version as written (HTML without the injected policy), where the user
 * picks in the system's save dialog, as the Mac's saveArtifact; a download in a browser.
 */
async function saveAs(content: ArtifactContent, bridge: Bridge): Promise<string | null> {
  const name = fileName(content.title, content.kind);
  if (!bridge.native) {
    const type = content.kind === "html" ? "text/html" : "text/plain";
    download(name, new Blob([savedText(content)], { type: `${type};charset=utf-8` }));
    return null;
  }
  return bridge.saveFile(name, { text: savedText(content) });
}

/** The version shown, read once per version; `retry` reads it again after a failure. */
function useVersion(id: string, version: number) {
  const { actions } = useStore();
  const [read, setRead] = useState<{ key: string; content: ArtifactContent | null } | null>(null);
  const [tries, setTries] = useState(0);
  const key = `${id}:${String(version)}:${String(tries)}`;
  useEffect(() => {
    let current = true;
    void actions.artifactVersion(id, version).then((content) => {
      if (current) setRead({ key, content });
    });
    return () => {
      current = false;
    };
  }, [actions, id, version, key]);
  const done = read?.key === key ? read : null;
  return {
    content: done?.content ?? null,
    failed: done !== null && done.content === null,
    retry: () => {
      setTries((n) => n + 1);
    },
  };
}
