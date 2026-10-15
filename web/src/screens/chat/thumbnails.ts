import { useSyncExternalStore } from "react";

/**
 * Thumbnails of images attached to drafts on this page, by attachment id. They live as
 * long as the page, so a draft keeps them while another chat is open; after a reload the
 * draft's files show by name only.
 */
const urls = new Map<string, string>();
const listeners = new Set<() => void>();

function changed(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Keeps a thumbnail of an attached image. */
export function keepThumbnail(id: string, file: File): void {
  if (!file.type.startsWith("image/")) return;
  urls.set(id, URL.createObjectURL(file));
  changed();
}

/** Lets an attachment's thumbnail go, once it was removed or sent. */
export function dropThumbnail(id: string): void {
  const url = urls.get(id);
  if (url === undefined) return;
  urls.delete(id);
  URL.revokeObjectURL(url);
  changed();
}

export function useThumbnail(id: string): string | null {
  return useSyncExternalStore(subscribe, () => urls.get(id) ?? null);
}
