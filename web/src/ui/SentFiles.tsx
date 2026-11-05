import { useEffect, useState, type ComponentType } from "react";
import { sizeText } from "../format.ts";
import { useStore } from "../store/context.ts";
import type { SentFile } from "../transcript/build.ts";
import { isImage, typeTag, useSentImage } from "./sentFile.ts";

export interface ImageViewer {
  // The attachment, for a viewer outside the page.
  id?: string | undefined;
  url: string;
  alt: string;
  onClose: () => void;
}

interface Props {
  files: SentFile[];
  // The client's own full-size view, and its way of handing a file to the user.
  Viewer: ComponentType<ImageViewer>;
  save: (filename: string, blob: Blob) => void;
  // The message's event, when no bubble carries it.
  ev?: string | undefined;
}

/** A message's images, then its other files; the images keep a fixed box, as no size is stored. */
export function SentFiles({ files, Viewer, save, ev }: Props) {
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
        <FileRow key={`${String(file.id)}.${String(index)}`} file={file} save={save} />
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

function FileRow({ file, save }: { file: SentFile; save: Props["save"] }) {
  const { actions } = useStore();
  const { id } = file;
  const [gone, setGone] = useState(false);
  const [failed, setFailed] = useState(false);
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

  const open = async (from: string) => {
    setFailed(false);
    const found = await actions.sentFile(from);
    if (found === "gone") setGone(true);
    else if (found === null) setFailed(true);
    else save(file.filename, found);
  };

  const size = file.size === null ? null : sizeText(file.size);
  const note = gone ? "Deleted" : failed ? "Could not open" : size;
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
    <button className="sf-file" onClick={() => void open(id)}>
      {content}
    </button>
  );
}
