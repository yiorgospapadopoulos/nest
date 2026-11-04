import { useEffect, useState } from "react";
import type { Actions } from "../../store/actions.ts";
import { useStore } from "../../store/context.ts";
import type { ResultImage, SentFile } from "../../transcript/build.ts";
import { SentFiles, type ImageViewer } from "../../ui/SentFiles.tsx";
import { Sheet } from "../../ui/Sheet.tsx";
import { download } from "../artifacts/files.ts";

// Each image's object URL, or null when it could not be had, fetched once per page: the
// API wants the device's credentials, so it is read as data rather than linked.
const loaded = new Map<string, Promise<string | null>>();

function urlOf(actions: Actions, id: string): Promise<string | null> {
  let url = loaded.get(id);
  if (url === undefined) {
    url = actions.attachment(id).then((blob) => (blob === null ? null : URL.createObjectURL(blob)));
    loaded.set(id, url);
  }
  return url;
}

/** Loading (undefined), unavailable (null) or its URL. */
function useImage(id: string): string | null | undefined {
  const { actions } = useStore();
  const [url, setUrl] = useState<{ id: string; url: string | null } | null>(null);
  useEffect(() => {
    void urlOf(actions, id).then((found) => {
      setUrl({ id, url: found });
    });
  }, [actions, id]);
  return url?.id === id ? url.url : undefined;
}

interface Props {
  images: ResultImage[];
  // What the images came from, for their description.
  from: string;
}

/** A tool result's images as thumbnails (B59); one opens full size on a tap. */
export function ResultImages({ images, from }: Props) {
  return (
    <div className="timgs">
      {images.map((image, index) => (
        <Thumbnail key={`${image.id}.${String(index)}`} id={image.id} from={from} />
      ))}
    </div>
  );
}

function Thumbnail({ id, from }: { id: string; from: string }) {
  const url = useImage(id);
  const [open, setOpen] = useState(false);
  if (url === undefined) return <span className="timg wait" aria-hidden="true" />;
  if (url === null) return <span className="timg none">Image unavailable</span>;
  const alt = `Image from ${from}`;
  return (
    <>
      <button
        className="timg"
        aria-label="Open image"
        onClick={() => {
          setOpen(true);
        }}
      >
        <img src={url} alt={alt} />
      </button>
      {open && (
        <FullImage
          url={url}
          alt={alt}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </>
  );
}

function FullImage({ url, alt, onClose }: ImageViewer) {
  return (
    <Sheet title="Image" full onClose={onClose}>
      <img className="timg-full" src={url} alt={alt} />
    </Sheet>
  );
}

/** A message's sent images and files, on the phone. */
export function Sent({ files, ev }: { files: SentFile[]; ev?: string | undefined }) {
  return <SentFiles files={files} Viewer={FullImage} save={download} ev={ev} />;
}
