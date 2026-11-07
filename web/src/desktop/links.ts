// Links in the desktop window open in the system's browser or mail app, as the Mac's
// NSWorkspace.open, and never replace Nest's own page. A page on this computer (a dev
// server) opens in a Nest browser window next to the work, as the Tauri side's own
// navigation rule does (desktop/src-tauri/src/external.rs).
import { loopbackOrigin, safeLink, type Bridge } from "./bridge.ts";

/** Opens a link from a button: web and mail links only (`safeLink`). */
export function openLink(url: string, bridge: Pick<Bridge, "openExternal" | "openBrowserWindow">) {
  const link = safeLink(url);
  if (link === null) return;
  if (loopbackOrigin(link) !== null) void bridge.openBrowserWindow(link);
  else void bridge.openExternal(link);
}

/**
 * Handles a click on a link anywhere in the window: an absolute web or mail link goes to
 * the system, any other link is held back (a relative one would load into Nest's window).
 * In-page anchors and downloads of the page's own files work as in a browser. Whether the
 * click was a link's.
 */
export function routeLinkClick(
  event: MouseEvent,
  bridge: Pick<Bridge, "openExternal" | "openBrowserWindow">,
): boolean {
  if (event.button !== 0 && event.button !== 1) return false;
  const target = event.target;
  const link = target instanceof Element ? target.closest("a[href]") : null;
  if (!(link instanceof HTMLAnchorElement)) return false;
  const href = link.getAttribute("href") ?? "";
  if (href.startsWith("#")) return false;
  if (link.hasAttribute("download") && /^(blob|data):/.test(href)) return false;
  event.preventDefault();
  openLink(href, bridge);
  return true;
}

/** The bug report's new issue opens on GitHub only, whatever address came back with it. */
export function isGitHubIssue(address: string): boolean {
  try {
    const url = new URL(address);
    return url.protocol === "https:" && url.hostname === "github.com";
  } catch {
    return false;
  }
}
