import { useState } from "react";

// Chats folded out, kept while the app runs, as the sidebar's folds on desktop. A row is
// made again whenever the list comes back from a chat.
const foldedOut = new Set<string>();

/** Whether the chat's earlier worktrees are folded out, and the toggle. */
export function useEarlierOpen(chat: string): [boolean, () => void] {
  const [open, setOpen] = useState(() => foldedOut.has(chat));
  return [
    open,
    () => {
      if (open) foldedOut.delete(chat);
      else foldedOut.add(chat);
      setOpen(!open);
    },
  ];
}
