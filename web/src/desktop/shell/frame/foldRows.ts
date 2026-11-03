// Which Needs you and Goals rows are open, as the Mac's shell.foldedRows: kept while the app
// runs, by row key; a row the user never toggled follows its own default.
import { useSyncExternalStore } from "react";
import type { Approval } from "../../../api/types.ts";

const open = new Map<string, boolean>();
const listeners = new Set<() => void>();
let version = 0;

function changed() {
  version += 1;
  for (const listener of [...listeners]) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * A pending approval's row key. A chat's review comments keep one row while the daemon
 * supersedes them with the rest after each send (B101).
 */
export function approvalFoldKey(approval: Pick<Approval, "id" | "kind" | "session_id">): string {
  return approval.kind === "review_comments"
    ? `review_comments-${approval.session_id}`
    : `approval-${approval.id}`;
}

export function setRowOpen(key: string, value: boolean): void {
  open.set(key, value);
  changed();
}

/**
 * Opens an approval's Needs you row, as a click on the pill's approval does; with the
 * project's panel opened on Needs you (Shell.showNeedsYou) it shows in place.
 */
export function unfoldApproval(approval: Pick<Approval, "id" | "kind" | "session_id">): void {
  setRowOpen(approvalFoldKey(approval), true);
}

/** Whether the row is open, and its toggle. */
export function useRowOpen(key: string, openByDefault: boolean): [boolean, () => void] {
  useSyncExternalStore(
    subscribe,
    () => version,
    () => version,
  );
  const value = open.get(key) ?? openByDefault;
  return [
    value,
    () => {
      setRowOpen(key, !value);
    },
  ];
}
