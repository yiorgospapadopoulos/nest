import { useEffect, useState, type ComponentType } from "react";
import { sizeText } from "../format.ts";
import { useStore } from "../store/context.ts";
import type { SentFile } from "../transcript/build.ts";
import type { FileSource } from "./useFileView.tsx";
import { isImage, typeTag, useSentImage } from "./sentFile.ts";

export interface ImageViewer {
  // The attachment, for a viewer outside the page.
  id?: string | undefined;
  url: string;
  alt: string;
  onClose: () => void;
}

export interface FileViewer {
  source: FileSource;
  onClose: () => void;
}

interface Props {
  files: SentFile[];
  // The client's own full-size view of an image, and its file viewer for the rest.
  Viewer: ComponentType<ImageViewer>;
  FileViewer: ComponentType<FileViewer>;
  // The message's event, when no bubble carries it.
  ev?: string | undefined;
}

/** A message's images, then its other files; the images keep a fixed box, as no size is stored. */
export function SentFiles({ files, Viewer, FileViewer, ev }: Props) {
  const images = files.filter(isImage);
  const others = files.filter((file) => !isImage(file));
  return (
    <div className="sf" data-ev={ev}>
      {images.length > 0 && (
        <div className="sf-imgs">
          {images.map((file, index) => (
            <SentImage key={`${String(file.id)}.${String(index)}`} file={file} Viewer={Viewer} />
          ))}
        </div>
      )}
      {others.map((file, index) => (
        <FileRow key={`${String(file.id)}.${String(index)}`} file={file} FileViewer={FileViewer} />
      ))}
    </div>
  );
}

function SentImage({ file, Viewer }: { file: SentFile; Viewer: Props["Viewer"] }) {
  const image = useSentImage(file.id ?? "");
  const [open, setOpen] = useState(false);
  if (image === undefined) return <span className="sf-img wait" aria-hidden="true" />;
  if (image === "gone") return <span className="sf-img gone">Image deleted</span>;
  if (image === "failed") return <span className="sf-img none">Image not available</span>;
  return (
    <>
      <button
        className="sf-img"
        aria-label={`Open ${file.filename}`}
        onClick={() => {
          setOpen(true);
        }}
      >
        <img src={image.url} alt={file.filename} />
      </button>
      {open && (
        <Viewer
          id={file.id ?? ""}
          url={image.url}
          alt={file.filename}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </>
  );
}

function FileRow({ file, FileViewer }: { file: SentFile; FileViewer: Props["FileViewer"] }) {
  const { actions } = useStore();
  const { id } = file;
  const [gone, setGone] = useState(false);
  const [source, setSource] = useState<FileSource | null>(null);
  useEffect(() => {
    if (id === null) return;
    let live = true;
    void actions.sentFileGone(id).then((deleted) => {
      if (live && deleted) setGone(true);
    });
    return () => {
      live = false;
    };
  }, [actions, id]);

  const size = file.size === null ? null : sizeText(file.size);
  const note = gone ? "Deleted" : size;
  const content = (
    <>
      <span className="sf-tile" aria-hidden="true">
        {typeTag(file.filename)}
      </span>
      <span className="sf-name">{file.filename}</span>
      {note !== null && <span className="sf-size">{note}</span>}
    </>
  );
  if (id === null || gone)
    return <div className={gone ? "sf-file gone" : "sf-file"}>{content}</div>;
  return (
    <>
      <button
        className="sf-file"
        onClick={() => {
          setSource({ kind: "sent", id, name: file.filename, mediaType: file.mediaType });
        }}
      >
        {content}
      </button>
      {source !== null && (
        <FileViewer
          source={source}
          onClose={() => {
            setSource(null);
          }}
        />
      )}
    </>
  );
}
