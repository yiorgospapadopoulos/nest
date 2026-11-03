// Terminal, browser and run output panes, ported from NestKit's ToolPane.swift.
import { paneKind, type PaneKind } from "./workspace.ts";

export type ToolKind = Exclude<PaneKind, "chat">;

export interface ToolPane {
  id: string;
  kind: ToolKind;
  // The folder a terminal's shell starts in, or whose run an output pane shows.
  folder: string | null;
  // The address a browser shows; null before the first page.
  url: string | null;
  // The chat a run output pane opened from, which the run's routes go through.
  session: string | null;
}

function newId(kind: ToolKind): string {
  return `${kind}:${crypto.randomUUID()}`;
}

/** A folder without a trailing slash, `.` or `..` parts. */
export function normalizedFolder(folder: string): string {
  const absolute = folder.startsWith("/");
  const parts: string[] = [];
  for (const part of folder.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") parts.pop();
    else parts.push(part);
  }
  const joined = parts.join("/");
  return absolute ? `/${joined}` : joined === "" ? "." : joined;
}

export function terminalPane(folder: string): ToolPane {
  return {
    id: newId("terminal"),
    kind: "terminal",
    folder: normalizedFolder(folder),
    url: null,
    session: null,
  };
}

export function browserPane(url: string | null = null): ToolPane {
  return { id: newId("browser"), kind: "browser", folder: null, url, session: null };
}

export function runPane(folder: string, session: string): ToolPane {
  return { id: newId("run"), kind: "run", folder, url: null, session };
}

export function isToolPane(id: string): boolean {
  return paneKind(id) !== "chat";
}

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]);

/** The host of an address typed without a scheme, and whether a port follows it. */
function hostOf(text: string): { host: string; hasPort: boolean } {
  const authority = /^[^/?#]*/.exec(text)?.[0] ?? "";
  if (authority.startsWith("[")) {
    const end = authority.indexOf("]");
    if (end !== -1) {
      return {
        host: authority.slice(0, end + 1),
        hasPort: authority.slice(end + 1).startsWith(":"),
      };
    }
  }
  const colon = authority.indexOf(":");
  if (colon === -1) return { host: authority, hasPort: false };
  return { host: authority.slice(0, colon), hasPort: /^\d+$/.test(authority.slice(colon + 1)) };
}

/**
 * What the browser opens for what was typed, as the Mac's BrowserAddress: a full address
 * as typed; a bare port (3000 or :3000) on localhost; a local host, or any host with a
 * port, over http; a host with a dot over https; anything else is a web search. Null for
 * blank input.
 */
export function browserAddress(input: string): string | null {
  const text = input.trim();
  if (text === "") return null;
  const bare = text.startsWith(":") ? text.slice(1) : text;
  if (/^\d+$/.test(bare)) {
    const port = Number(bare);
    if (port >= 1 && port <= 65535) return `http://localhost:${String(port)}`;
  }
  if (text.includes("://") || text.startsWith("about:")) return text;
  if (!/\s/.test(text)) {
    const { host, hasPort } = hostOf(text);
    if (LOCAL_HOSTS.has(host.toLowerCase()) || hasPort) return `http://${text}`;
    if (host.includes(".")) return `https://${text}`;
  }
  return `https://duckduckgo.com/?q=${encodeURIComponent(text)}`;
}

/** The pane header's name: a terminal's or run's folder name, a browser's host. */
export function toolTitle(pane: ToolPane): string {
  if (pane.kind === "browser") {
    try {
      const host = pane.url === null ? "" : new URL(pane.url).hostname;
      return host === "" ? "Browser" : host;
    } catch {
      return "Browser";
    }
  }
  const name = pane.folder?.split("/").filter(Boolean).at(-1) ?? "";
  return name === "" ? "Terminal" : name;
}

// Marks that reorder text on screen, so a command would read differently from what runs.
const DIRECTION_MARKS = /[\u{61C}\u{200E}\u{200F}\u{202A}-\u{202E}\u{2066}-\u{2069}]/gu;
const NEWLINES = new RegExp(`[\\n\\r\\v\\f\\x85${String.fromCharCode(0x2028, 0x2029)}]`, "u");
const CONTROLS = /[\p{Cc}]/gu;

/**
 * The text typed into a shell to run a command from a chat: the command and the newline
 * that runs it, without control characters (tabs aside) or direction marks. Null when
 * nothing is left, or when it spans lines, since each line would run on its own.
 */
export function terminalLine(command: string): string | null {
  const kept = command
    .replace(DIRECTION_MARKS, "")
    .replace(CONTROLS, (c) => (c === "\t" || NEWLINES.test(c) ? c : ""))
    .trim();
  if (kept === "" || NEWLINES.test(kept)) return null;
  return `${kept}\n`;
}
