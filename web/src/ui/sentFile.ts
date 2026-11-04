import { useEffect, useState } from "react";
import type { QueuedAttachment } from "../api/types.ts";
import type { Actions } from "../store/actions.ts";
import { useStore } from "../store/context.ts";
import type { SentFile } from "../transcript/build.ts";

// The types the daemon serves inline; anything else downloads, so it shows as a file row.
const RASTER = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);

export function isImage(file: SentFile): boolean {
  return file.id !== null && file.mediaType !== null && RASTER.has(file.mediaType);
}

export function fromQueued(attachment: QueuedAttachment): SentFile {
  return {
    id: attachment.id,
    filename: attachment.filename,
    mediaType: attachment.media_type,
    size: attachment.size,
  };
}

/** The short type a file row's tile shows: "PDF", or "FILE" with no usable extension. */
export function typeTag(filename: string): string {
  const dot = filename.lastIndexOf(".");
  const extension = dot > 0 ? filename.slice(dot + 1) : "";
  return /^[a-z0-9]{1,4}$/i.test(extension) ? extension.toUpperCase() : "FILE";
}

export type LoadedImage = { url: string } | "gone" | "failed";

// Each image's object URL or its deletion, fetched once per page: the API wants the
// device's credentials, so it is read as data rather than linked. A failure is not kept,
// so the image is tried again when it next comes on screen.
const images = new Map<string, Promise<LoadedImage>>();

async function fetchImage(actions: Actions, id: string): Promise<LoadedImage> {
  const found = await actions.sentFile(id);
  if (found === "gone") return "gone";
  if (found === null) {
    images.delete(id);
    return "failed";
  }
  return { url: URL.createObjectURL(found) };
}

/** A sent image: loading (undefined), its URL, deleted or failed. */
export function useSentImage(id: string): LoadedImage | undefined {
  const { actions } = useStore();
  const [image, setImage] = useState<{ id: string; loaded: LoadedImage } | null>(null);
  useEffect(() => {
    let live = true;
    let load = images.get(id);
    if (load === undefined) {
      load = fetchImage(actions, id);
      images.set(id, load);
    }
    void load.then((loaded) => {
      if (live) setImage({ id, loaded });
    });
    return () => {
      live = false;
    };
  }, [actions, id]);
  return image?.id === id ? image.loaded : undefined;
}
