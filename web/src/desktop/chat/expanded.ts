// Which transcript rows are opened, kept outside the rows as the Mac's shell.expandedItems:
// a long chat draws only the rows near the screen, so a row scrolled away and drawn again
// opens as the reader left it. Kept for the app's run, per chat.
import { useCallback, useSyncExternalStore } from "react";

const opened = new Set<string>();
const listeners = new Set<() => void>();

const keyOf = (chat: string, id: string) => `${chat}\n${id}`;

function changed(): void {
  for (const listener of [...listeners]) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function isOpen(chat: string, id: string): boolean {
  return opened.has(keyOf(chat, id));
}

export function setOpen(chat: string, id: string, open: boolean): void {
  const key = keyOf(chat, id);
  if (opened.has(key) === open) return;
  if (open) opened.add(key);
  else opened.delete(key);
  changed();
}

/** Whether the row `id` of `chat` is open, and a toggle for it. */
export function useOpen(chat: string, id: string): [boolean, () => void] {
  const key = keyOf(chat, id);
  const open = useSyncExternalStore(
    subscribe,
    () => opened.has(key),
    () => false,
  );
  const toggle = useCallback(() => {
    if (opened.has(key)) opened.delete(key);
    else opened.add(key);
    changed();
  }, [key]);
  return [open, toggle];
}

// The turn whose "Worked for 1m 12s" shows: the one under the pointer, as the Mac shows a
// turn's end while its reply is hovered.
let hoveredTurn: string | null = null;
const turnListeners = new Set<() => void>();

export function hoverTurn(turn: string | null): void {
  if (hoveredTurn === turn) return;
  hoveredTurn = turn;
  for (const listener of [...turnListeners]) listener();
}

function subscribeTurn(listener: () => void): () => void {
  turnListeners.add(listener);
  return () => {
    turnListeners.delete(listener);
  };
}

export function useTurnShown(turn: string): boolean {
  return useSyncExternalStore(
    subscribeTurn,
    () => hoveredTurn === turn,
    () => false,
  );
}

/** Each row's turn end, by row key: the turn end line after it, or its own. */
export function turnEnds(rows: readonly { key: string; kind: string }[]): Map<string, string> {
  const ends = new Map<string, string>();
  let pending: string[] = [];
  for (const { key, kind } of rows) {
    pending.push(key);
    if (kind === "turn") {
      for (const row of pending) ends.set(row, key);
      pending = [];
    }
  }
  return ends;
}
