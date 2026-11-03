import { isDraft } from "../panes.ts";

// The chat Init starts in a plain folder (NestKit's GitInit.prompt); the user sends it.
export const GIT_INIT =
  "Initialize this folder as a git repository: run git init with main as the default branch and add a .gitignore that fits what is in this folder. Do not commit; Nest handles commits.";

/**
 * Whether closing a draft pane leaves Init's text behind in the project's new chat
 * composer, which the start view shares: on the Mac it lived in that draft only
 * (Shell.setUpGit), so it goes with the last draft pane, unless the user changed it.
 */
export function initTextLeft(closing: string, openPanes: string[], draftText: string): boolean {
  if (!isDraft(closing) || draftText !== GIT_INIT) return false;
  return !openPanes.some((pane) => pane !== closing && isDraft(pane));
}
