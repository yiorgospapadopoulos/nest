import type { ArtifactKind } from "../../api/types.ts";

const EXTENSIONS: Record<ArtifactKind, string> = { markdown: "md", html: "html" };
const TYPES: Record<ArtifactKind, string> = { markdown: "text/markdown", html: "text/html" };
// Characters no file system takes in a name, and control characters.
// eslint-disable-next-line no-control-regex
const UNSAFE = /[\\/:*?"<>|\u0000-\u001f\u007f]+/g;
const LONGEST = 100;

/** "Options compared.md": the title made safe for a file name. */
export function fileName(title: string, kind: ArtifactKind): string {
  const base = title
    .replace(UNSAFE, " ")
    .replace(/\s+/g, " ")
    .trim()
    // A leading dot would hide the file.
    .replace(/^\.+\s*/, "")
    .slice(0, LONGEST)
    .trim();
  return `${base || "Artifact"}.${EXTENSIONS[kind]}`;
}

/** Hands the content to the browser as a download, as written (no injected policy). */
export function saveFile(title: string, kind: ArtifactKind, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: `${TYPES[kind]};charset=utf-8` }));
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName(title, kind);
  document.body.append(link);
  link.click();
  link.remove();
  // Safari reads the file after the click returns.
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 1000);
}
