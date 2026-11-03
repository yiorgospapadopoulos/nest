// What the user chose in a question card, kept per approval as the Mac's ApprovalsStore
// keeps choices and others: the card in the chat and the one in Needs you show the same.
import { useSyncExternalStore } from "react";

export interface QuestionPicks {
  // The labels chosen per question; a question not here keeps its recommended ones.
  picked: Record<string, string[]>;
  // Other's text per question while Other is chosen, else null.
  others: Record<string, string | null>;
}

const EMPTY: QuestionPicks = { picked: {}, others: {} };
const picks = new Map<string, QuestionPicks>();
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function update(id: string, change: Partial<QuestionPicks>): void {
  picks.set(id, { ...(picks.get(id) ?? EMPTY), ...change });
  for (const listener of [...listeners]) listener();
}

/** The approval's choices and their setters, shared by every card of it. */
export function useQuestionPicks(id: string) {
  const current = useSyncExternalStore(
    subscribe,
    () => picks.get(id) ?? EMPTY,
    () => EMPTY,
  );
  return {
    ...current,
    setPicked: (picked: Record<string, string[]>) => {
      update(id, { picked });
    },
    setOthers: (others: Record<string, string | null>) => {
      update(id, { others });
    },
  };
}
