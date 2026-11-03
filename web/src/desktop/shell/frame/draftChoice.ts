// Where the next new chat of a project starts, when a click chose it: the branch map's rows
// (A8) start a chat there. The draft's "Work on" picker takes it once, when it first shows.
import type { NewChatChoice } from "../../chat/placePicker.ts";

const next = new Map<string, NewChatChoice>();

export function setNextDraftChoice(repo: string, choice: NewChatChoice): void {
  next.set(repo, choice);
}

/** The choice set for the project's next draft, once; null when none was. */
export function takeNextDraftChoice(repo: string): NewChatChoice | null {
  const choice = next.get(repo) ?? null;
  next.delete(repo);
  return choice;
}
