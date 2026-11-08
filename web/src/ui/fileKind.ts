// What the file viewer shows a file as (B144). The daemon names a sent file's type; a file a
// message names comes untyped, so its name and first bytes decide.

export type FileKind = "image" | "pdf" | "video" | "text" | "other";

// Images a browser draws; SVG shows as its text, so nothing in it runs.
const IMAGES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);
const TEXT_TYPES = new Set([
  "application/javascript",
  "application/json",
  "application/sql",
  "application/toml",
  "application/x-sh",
  "application/x-yaml",
  "application/xml",
  "application/yaml",
]);
const BY_EXTENSION: Record<string, FileKind> = {
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  pdf: "pdf",
  mp4: "video",
  m4v: "video",
  mov: "video",
  webm: "video",
};
// Types that say nothing about the content.
const UNSURE = new Set(["", "application/octet-stream", "video/mp2t"]);
const SNIFF_BYTES = 8192;

export function isTextType(type: string): boolean {
  return (
    type.startsWith("text/") ||
    TEXT_TYPES.has(type) ||
    type.endsWith("+json") ||
    type.endsWith("+xml")
  );
}

function byType(type: string): FileKind | null {
  if (UNSURE.has(type)) return null;
  if (IMAGES.has(type)) return "image";
  if (type === "application/pdf") return "pdf";
  if (type.startsWith("video/")) return "video";
  if (isTextType(type)) return "text";
  return "other";
}

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

/** UTF-8 text with no NUL byte; a character cut off at the end is fine. */
export function looksLikeText(head: Uint8Array): boolean {
  if (head.includes(0)) return false;
  try {
    new TextDecoder("utf-8", { fatal: true }).decode(head, { stream: true });
    return true;
  } catch {
    return false;
  }
}

/** The kind to show a file as, by its type, then its extension, then its first bytes. */
export async function kindOf(name: string, type: string, blob: Blob): Promise<FileKind> {
  const known = byType(type);
  if (known !== null) return known;
  const byName = BY_EXTENSION[extensionOf(name)];
  if (byName !== undefined) return byName;
  const head = new Uint8Array(await blob.slice(0, SNIFF_BYTES).arrayBuffer());
  return looksLikeText(head) ? "text" : "other";
}
