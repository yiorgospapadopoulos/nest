import { useEffect, useState } from "react";

/** How the frame gets its page: an address, the page inline, or nothing yet. */
export type FrameSource = { src: string } | { srcDoc: string } | Record<string, never>;

/**
 * The page for the artifact's frame, as the phone reader stages it (B117). In the desktop
 * app the page is served once from its own nest-artifact: address with the artifact policy
 * as a header: a srcdoc frame would inherit the window's stricter policy, under which the
 * page's scripts cannot run. While it is staged the frame gets nothing; if staging fails,
 * srcdoc, which the window's policy then keeps from running scripts. Outside the desktop
 * app, srcdoc. A page staged after its frame went is released, as is one never loaded.
 */
export function useStagedPage(page: string): FrameSource {
  const tauri = window.__TAURI__;
  const [staged, setStaged] = useState<{ page: string; url: string | null } | null>(null);
  useEffect(() => {
    if (tauri === undefined) return;
    const release = (url: string) => {
      tauri.core.invoke("release_artifact", { url }).catch(() => undefined);
    };
    let live = true;
    let url: string | null = null;
    tauri.core.invoke("stage_artifact", { html: page }).then(
      (result) => {
        url = String(result);
        if (live) setStaged({ page, url });
        else release(url);
      },
      () => {
        if (live) setStaged({ page, url: null });
      },
    );
    return () => {
      live = false;
      // The page is served once; this drops it if the frame went before loading it.
      if (url !== null) release(url);
    };
  }, [tauri, page]);
  if (tauri === undefined) return { srcDoc: page };
  if (staged?.page !== page) return {};
  return staged.url === null ? { srcDoc: page } : { src: staged.url };
}
