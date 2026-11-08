import { useEffect, useMemo, useState, type ReactNode } from "react";
import { sizeText } from "../format.ts";
import { useStore } from "../store/context.ts";
import { kindOf, type FileKind } from "./fileKind.ts";
import { PdfView } from "./PdfView.tsx";
import { TextLines } from "./TextLines.tsx";

// The file viewer's content (B144): a sent file or a file a message names, as a PDF, a
// video, an image or text with line numbers. It views and never edits; each client puts it
// in its own sheet.

// Text past this shows only in part; Save gives all of it.
const MAX_TEXT_CHARS = 2_000_000;

export type FileSource =
  | { kind: "sent"; id: string; name: string; mediaType: string | null }
  | { kind: "named"; session: string; path: string; line: number | null };

type Loaded =
  | { state: "loading" }
  | { state: "gone" }
  | { state: "failed" }
  | { state: "ready"; blob: Blob; kind: FileKind; text: string | null };

export function nameOf(source: FileSource): string {
  if (source.kind === "sent") return source.name;
  return source.path.slice(source.path.lastIndexOf("/") + 1) || source.path;
}

function useLoaded(source: FileSource): Loaded {
  const { actions } = useStore();
  // What was loaded, and for which source: another source is loading until it arrives.
  const [loaded, setLoaded] = useState<{ source: FileSource; loaded: Loaded } | null>(null);
  useEffect(() => {
    let live = true;
    const done = (result: Loaded) => {
      if (live) setLoaded({ source, loaded: result });
    };
    const fetched =
      source.kind === "sent"
        ? actions.sentFile(source.id)
        : actions.namedFile(source.session, source.path);
    void fetched.then(async (found) => {
      if (found === "gone" || found === null) {
        done({ state: found === "gone" ? "gone" : "failed" });
        return;
      }
      const type = source.kind === "sent" ? (source.mediaType ?? "") : "";
      const kind = await kindOf(nameOf(source), type, found);
      const text = kind === "text" ? await found.slice(0, MAX_TEXT_CHARS).text() : null;
      done({ state: "ready", blob: found, kind, text });
    });
    return () => {
      live = false;
    };
  }, [actions, source]);
  return loaded?.source === source ? loaded.loaded : { state: "loading" };
}

function useObjectUrl(blob: Blob | null, type: string): string | null {
  const url = useMemo(
    () =>
      blob === null
        ? null
        : URL.createObjectURL(type === "" ? blob : blob.slice(0, blob.size, type)),
    [blob, type],
  );
  useEffect(
    () => () => {
      if (url !== null) URL.revokeObjectURL(url);
    },
    [url],
  );
  return url;
}

export interface FileViewParts {
  title: string;
  // Its size and, for a PDF, the page in view or, for text, its lines.
  meta: string | null;
  // The file's data once loaded, to save.
  blob: Blob | null;
  body: ReactNode;
}

/** The parts of the viewer for a file: each client lays them out in its sheet. The source is
 * loaded again whenever it changes, so callers keep it in state. */
export function useFileView(source: FileSource): FileViewParts {
  const loaded = useLoaded(source);
  const [page, setPage] = useState<{ page: number; pages: number } | null>(null);
  const [pdfFailed, setPdfFailed] = useState(false);
  const ready = loaded.state === "ready" ? loaded : null;
  const mediaType =
    ready?.kind === "video" && source.kind === "sent" ? (source.mediaType ?? "") : "";
  const url = useObjectUrl(
    ready !== null && ready.kind !== "text" && ready.kind !== "other" ? ready.blob : null,
    mediaType,
  );
  const title = nameOf(source);
  const line = source.kind === "named" ? source.line : null;

  let body: ReactNode;
  if (loaded.state === "loading") body = <p className="fv-empty">Loading</p>;
  else if (loaded.state === "gone")
    body = <p className="fv-empty">This file is not there any more.</p>;
  else if (loaded.state === "failed")
    body = <p className="fv-empty">The file could not be opened.</p>;
  else if (loaded.kind === "text") {
    body = (
      <TextLines
        text={loaded.text ?? ""}
        name={title}
        line={line}
        cut={loaded.blob.size > MAX_TEXT_CHARS}
      />
    );
  } else if (loaded.kind === "pdf" && !pdfFailed) {
    body = (
      <PdfView
        data={loaded.blob}
        onPage={(at, pages) => {
          setPage({ page: at, pages });
        }}
        onFailed={() => {
          setPdfFailed(true);
        }}
      />
    );
  } else if (loaded.kind === "video" && url !== null) {
    body = <video className="fv-video" src={url} controls playsInline />;
  } else if (loaded.kind === "image" && url !== null) {
    body = <img className="fv-image" src={url} alt={title} />;
  } else {
    body = <p className="fv-empty">No preview for this file. Save it to open it in another app.</p>;
  }

  const parts: string[] = [];
  if (ready !== null) parts.push(sizeText(ready.blob.size));
  if (ready?.kind === "pdf" && page !== null && !pdfFailed) {
    parts.push(`page ${String(page.page)} of ${String(page.pages)}`);
  }
  return {
    title,
    meta: parts.length === 0 ? null : parts.join(" · "),
    blob: ready?.blob ?? null,
    body,
  };
}
