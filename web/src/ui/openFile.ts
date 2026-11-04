import { createContext } from "react";

export type OpenFile = (path: string) => void;

/**
 * What a click on a file a message names does. Only the desktop's chats provide it, for a
 * chat whose folder is on this computer; elsewhere those stay text.
 */
export const OpenFileContext = createContext<OpenFile | null>(null);
