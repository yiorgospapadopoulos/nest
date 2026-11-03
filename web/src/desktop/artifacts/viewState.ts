// What the Artifacts view keeps while it is away, as NestKit's ArtifactsStore does for the
// Mac's view: the scope it last showed, whether it shows the wide list, and the reader's
// selection. One for the window, so a transcript card or a pixie's page can open a version.
import { useSyncExternalStore } from "react";
import { useShell, type Shell } from "../shell/context.ts";
import type { ArtifactSelection } from "./query.ts";

interface ViewState {
  // The scope the view showed last; a new one starts on its narrow list.
  scope: string | null;
  wide: boolean;
  selection: ArtifactSelection | null;
}

let current: ViewState = { scope: null, wide: false, selection: null };
const listeners = new Set<() => void>();

function set(change: Partial<ViewState>): void {
  current = { ...current, ...change };
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useArtifactsView(): ViewState {
  return useSyncExternalStore(subscribe, () => current);
}

/** The view shows this scope: a new one starts on its narrow list. */
export function showScope(scope: string): void {
  if (current.scope !== scope) set({ scope, wide: false });
}

/** The scope switch, for the scope shown. */
export function setWide(wide: boolean): void {
  set({ wide });
}

export function select(selection: ArtifactSelection | null): void {
  const was = current.selection;
  if (was?.id === selection?.id && was?.version === selection?.version) return;
  set({ selection });
}

/**
 * A transcript card's Open, or a row of a pixie's page (Shell.openArtifact): the Artifacts
 * view of the tab on screen with that version in the reader, the card's chat focused.
 */
export function openArtifact(shell: Shell, id: string, version: number, chat?: string): void {
  shell.update((state) => {
    if (chat !== undefined && state.layout.contains(chat)) state.layout.focus(chat);
    state.view = "artifacts";
  });
  select({ id, version });
}

export function useOpenArtifact(): (id: string, version: number, chat?: string) => void {
  const shell = useShell();
  return (id, version, chat) => {
    openArtifact(shell, id, version, chat);
  };
}
