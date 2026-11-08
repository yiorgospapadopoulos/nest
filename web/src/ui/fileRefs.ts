// Finds what in a message names a file (B118): a markdown link with no scheme, and path-like
// text with an extension and an optional `:line`. The text is the agent's and untrusted, so
// this only decides what looks like a file; whoever opens one checks that it is safe to, on
// the Tauri side. The Mac's twin is `apple/Sources/NestKit/Presentation/FileReference.swift`.

export interface FileRef {
  start: number;
  end: number;
  path: string;
}

// Without a slash a name needs one of these: `a.b` is usually not a file.
const COMMON = new Set(
  (
    "bash bat c cc cfg cjs conf cpp cs css csv cts dart env ex exs fish go gradle graphql " +
    "h hpp hs htm html ini java js json jsonc jsx kt kts lock lua markdown md mdx mjs mm mts nix " +
    "php plist proto ps1 py pyi rb rs rst sass scala scss sh sql svelte swift tf toml ts tsv tsx " +
    "txt vue xml yaml yml zsh"
  ).split(" "),
);
// Projects named like files.
const NAMES = new Set(["node.js", "next.js", "nuxt.js", "vue.js", "deno.js", "three.js"]);
const EXTENSION = /^[a-z0-9]{1,12}$/;
const SCHEME = /^[a-z][a-z0-9+.-]*:/i;
const LINE_SUFFIX = /:\d+(?:[:-]\d+)?$/;
// Marks of a pattern or a shell word, not of a path someone would open.
const NOT_IN_PATH = /[\s:*?<>|"$\\{}]/;
// Control characters, here to be refused.
const CONTROL = new RegExp(`[${String.fromCharCode(0)}-${String.fromCharCode(31)}]`);
// What cannot stand right before a path: the rest of a URL, a variable, a glob.
const BEFORE = new Set(":\\$%#&*~");

const nameOf = (path: string) => path.slice(path.lastIndexOf("/") + 1);

function extensionOf(name: string): string | null {
  const dot = name.lastIndexOf(".");
  return dot <= 0 ? null : name.slice(dot + 1).toLowerCase();
}

/** Whether the first folder reads as a site: `example.com/a.md`. */
function startsWithHost(path: string): boolean {
  const first = path.slice(0, Math.max(path.indexOf("/"), 0));
  if (first.startsWith(".") || !first.includes(".")) return false;
  return !COMMON.has(extensionOf(first) ?? "");
}

function looksLikeFile(path: string): boolean {
  if (path === "" || path.startsWith("//") || path.startsWith("~")) return false;
  const extension = extensionOf(nameOf(path));
  if (extension === null) return false;
  if (!path.includes("/")) return COMMON.has(extension) && !NAMES.has(path.toLowerCase());
  return EXTENSION.test(extension) && /[a-z]/.test(extension) && !startsWithHost(path);
}

const isPathChar = (char: string) => /^[A-Za-z0-9_\-./@+]$/.test(char);
const isDigit = (char: string) => char >= "0" && char <= "9";

/** Where the `:line`, `:line:column` or `:line-line` at `at` ends; `at` without one. */
function lineEnd(text: string, at: number): number {
  const digits = (from: number) => {
    let index = from;
    while (isDigit(text.charAt(index))) index += 1;
    return index;
  };
  if (text.charAt(at) !== ":") return at;
  const line = digits(at + 1);
  if (line === at + 1) return at;
  const more = text.charAt(line);
  if (more !== ":" && more !== "-") return line;
  const second = digits(line + 1);
  return second === line + 1 ? line : second;
}

/** The files plain text names, in order. */
export function fileRefsIn(text: string): FileRef[] {
  const refs: FileRef[] = [];
  let at = 0;
  while (at < text.length) {
    if (!isPathChar(text.charAt(at))) {
      at += 1;
      continue;
    }
    let end = at;
    while (isPathChar(text.charAt(end))) end += 1;
    let stop = end;
    while (stop > at && text.charAt(stop - 1) === ".") stop -= 1;
    const path = text.slice(at, stop);
    const lineStop = stop === end ? lineEnd(text, stop) : stop;
    const next = text.charAt(lineStop);
    if (!BEFORE.has(text.charAt(at - 1)) && next !== "(" && looksLikeFile(path)) {
      refs.push({ start: at, end: lineStop, path });
    }
    at = Math.max(end, lineStop);
  }
  return refs;
}

/** The line a reference ends with: 42 for `a.ts:42`, `a.ts:42:7` or `a.ts:42-50`. */
export function lineIn(text: string): number | null {
  const found = /:(\d+)(?:[:-]\d+)?$/.exec(text.trim());
  return found === null ? null : Number(found[1]);
}

/** The file a whole code span names, if it is one path with an optional line. */
export function codeRef(code: string): string | null {
  const path = code.trim().replace(LINE_SUFFIX, "");
  return !NOT_IN_PATH.test(path) && looksLikeFile(path) ? path : null;
}

/** The file a markdown link with no scheme points at. */
export function linkRef(url: string): string | null {
  const target = url.trim();
  if (target === "" || target.startsWith("#") || target.startsWith("//")) return null;
  const hash = target.indexOf("#");
  const bare = (hash === -1 ? target : target.slice(0, hash)).replace(LINE_SUFFIX, "");
  if (SCHEME.test(bare)) return null;
  let path: string;
  try {
    path = decodeURIComponent(bare);
  } catch {
    return null;
  }
  if (CONTROL.test(path) || path.includes("\\") || path.endsWith("/")) return null;
  const name = nameOf(path);
  if (name === "." || name === ".." || startsWithHost(path)) return null;
  if (!path.includes("/") && name.includes(".") && !COMMON.has(extensionOf(name) ?? "")) {
    return null;
  }
  return path;
}
