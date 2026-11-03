// A tool result's images, read with the device's credentials as data rather than linked
// (B59): each one's object URL, or null when it could not be had, fetched once per page.
import { useEffect, useState } from "react";
import type { Actions } from "../../store/actions.ts";
import { useStore } from "../../store/context.ts";

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
export function useImage(id: string): string | null | undefined {
  const { actions } = useStore();
  const [url, setUrl] = useState<{ id: string; url: string | null } | null>(null);
  useEffect(() => {
    let live = true;
    void urlOf(actions, id).then((found) => {
      if (live) setUrl({ id, url: found });
    });
    return () => {
      live = false;
    };
  }, [actions, id]);
  return url?.id === id ? url.url : undefined;
}
