import { createContext } from "react";

// The line, when the message names one (`a.ts:42`).
export type OpenFile = (path: string, line: number | null) => void;

/**
 * What a click on a file a message names does: it opens in the file viewer for a chat the
 * daemon knows, or in the text editor for one only Claude Code knows, on the desktop. With
 * neither those stay text.
 */
export const OpenFileContext = createContext<OpenFile | null>(null);

export type ReadFile = (path: string) => Promise<Blob | null>;

/** Reads a file a message names from the chat's folder, for the images it shows (B144). */
export const ReadFileContext = createContext<ReadFile | null>(null);

export type CopyText = (text: string) => Promise<void>;

/** Copies a code block's text (B144): through the Mac app in its panes, else the browser's. */
export const CopyTextContext = createContext<CopyText>((text) =>
  navigator.clipboard.writeText(text),
);
