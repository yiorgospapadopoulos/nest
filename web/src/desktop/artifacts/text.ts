// The words and file rules the artifact views use, as NestKit's ArtifactText and
// ArtifactFile (ArtifactPresentation.swift).
import type { Artifact, ArtifactAuthor, ArtifactContent, ArtifactKind } from "../../api/types.ts";
import { sizeText } from "../../format.ts";
import { KIND_LABELS } from "../../screens/artifacts/view.ts";

/** Today's asks of a page: what is left of the day's limit. */
export interface AskCount {
  remaining: number;
  limit: number;
}

/** Who made it: the pixie, the chat, or "Deleted chat". */
export function origin(artifact: Artifact): string {
  if (artifact.pixie_name !== null) return artifact.pixie_name;
  if (artifact.chat_deleted || artifact.chat_title === null) return "Deleted chat";
  return artifact.chat_title;
}

/** "now", "9m", "2h 5m" or "3d", as the Mac's Elapsed.short. */
function elapsed(ms: number): string {
  const minutes = Math.floor(Math.max(0, ms) / 60_000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${String(minutes)}m`;
  if (minutes < 24 * 60) {
    const rest = minutes % 60;
    return `${String(Math.floor(minutes / 60))}h${rest > 0 ? ` ${String(rest)}m` : ""}`;
  }
  return `${String(Math.floor(minutes / (24 * 60)))}d`;
}

/** "now" or "9m ago". */
export function when(iso: string, now: Date): string {
  const shown = elapsed(now.getTime() - Date.parse(iso));
  return shown === "now" ? shown : `${shown} ago`;
}

export function asksText({ remaining, limit }: AskCount): string {
  const used = Math.min(limit, Math.max(0, limit - remaining));
  return `${String(used)} of ${String(limit)} asks today`;
}

/**
 * The reader's line under the title: the kind, who made it, and when this version was
 * saved, "Edited by you" when the user saved it; what the page stored, then today's asks.
 */
export function line(
  artifact: Artifact,
  author: ArtifactAuthor,
  saved: string,
  now: Date,
  stored: number,
  asks: AskCount | null,
): string {
  const made = author === "user" ? "Edited by you" : "saved";
  const parts = [KIND_LABELS[artifact.kind], origin(artifact), `${made} ${when(saved, now)}`];
  if (stored > 0) parts.push(`${sizeText(stored)} stored`);
  if (asks !== null) parts.push(asksText(asks));
  return parts.join(" · ");
}

export const ASKING = "Asking Claude…";

/** "Version 2 of 3". */
export function versionText(version: number, count: number): string {
  return `Version ${String(version)} of ${String(count)}`;
}

/** Slides and documents print themselves into a PDF (B88); other kinds have no export. */
export function exportsPdf(kind: ArtifactKind): boolean {
  return kind === "slides" || kind === "document";
}

const EXTENSIONS: Record<ArtifactKind, string> = {
  markdown: "md",
  slides: "md",
  document: "md",
  html: "html",
  design: "json",
  design_system: "json",
};
const LONGEST = 120;
// eslint-disable-next-line no-control-regex
const FORBIDDEN = /[/\\:*?"<>|\u0000-\u001f\u007f-\u009f]/g;

/** The text without characters a file name may not hold, its spaces folded, at most 120. */
function clean(text: string): string {
  return text
    .replace(FORBIDDEN, " ")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ")
    .replace(/^[. ]+|[. ]+$/g, "")
    .slice(0, LONGEST);
}

/** Save as file's name: the title, with the kind's extension. */
export function fileName(title: string, kind: ArtifactKind): string {
  return `${clean(title) || "Artifact"}.${EXTENSIONS[kind]}`;
}

/** Export PDF's file name. */
export function pdfName(title: string): string {
  return `${clean(title) || "Artifact"}.pdf`;
}

/** What Save as file writes: the content as saved, or a multi-file html page's built page. */
export function savedText(content: ArtifactContent): string {
  return content.kind === "html" && content.files.length > 0 ? content.page : content.content;
}
