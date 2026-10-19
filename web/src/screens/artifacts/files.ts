import type { ArtifactKind } from "../../api/types.ts";

const EXTENSIONS: Record<ArtifactKind, string> = {
  markdown: "md",
  html: "html",
  slides: "md",
  document: "md",
  design: "json",
  design_system: "json",
};
const TYPES: Record<ArtifactKind, string> = {
  markdown: "text/markdown",
  html: "text/html",
  slides: "text/markdown",
  document: "text/markdown",
  design: "application/json",
  design_system: "application/json",
};
// Characters no file system takes in a name, and control characters.
// eslint-disable-next-line no-control-regex
const UNSAFE = /[\\/:*?"<>|\u0000-\u001f\u007f]+/g;
const LONGEST = 100;

/** The text made safe for a file name; empty when nothing of it is. */
export function safeName(text: string): string {
  return (
    text
      .replace(UNSAFE, " ")
      .replace(/\s+/g, " ")
      .trim()
      // A leading dot would hide the file.
      .replace(/^\.+\s*/, "")
      .slice(0, LONGEST)
      .trim()
  );
}

/** "Options compared.md": the title made safe for a file name. */
export function fileName(title: string, kind: ArtifactKind): string {
  return `${safeName(title) || "Artifact"}.${EXTENSIONS[kind]}`;
}

/** Hands the content to the browser as a download, as written (no injected policy). */
export function saveFile(title: string, kind: ArtifactKind, content: string): void {
  download(fileName(title, kind), new Blob([content], { type: `${TYPES[kind]};charset=utf-8` }));
}

/** Hands the blob to the browser as a download under the name. */
export function download(name: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  // Safari reads the file after the click returns.
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 1000);
}
