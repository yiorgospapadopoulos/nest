// Rewinding to before a user message, ported from NestKit's RewindFlow (B59, IMP-02): the
// choices the sheet offers, why one cannot be chosen, and the one chosen to start with.
import type { Restore, RewindPreview } from "../../api/types.ts";

export type Purpose = "rewind" | "edit";

export const RESTORE_LABELS: Record<Restore, string> = {
  conversation: "Restore conversation",
  code: "Restore code",
  both: "Restore conversation and code",
};

export const RESTORE_SCOPES: Record<Restore, string> = {
  conversation:
    "Claude forgets this message and everything after it. Files stay as they are, and the message goes back into the composer.",
  code: "Only files are restored. The conversation stays as it is, and Claude is not told.",
  both: "Files go back to before this message, and Claude forgets it and everything after it. The message goes back into the composer.",
};

// A preview read (or null when it could not be), or undefined while it loads.
export type Loaded = RewindPreview | null | undefined;

export function changedCount(preview: RewindPreview): number {
  const files = preview.files_changed;
  return Array.isArray(files) ? files.length : files;
}

/** Edit always rewinds the conversation. */
export function choices(purpose: Purpose): Restore[] {
  return purpose === "edit" ? ["conversation", "both"] : ["conversation", "code", "both"];
}

const FAILED = "What would change could not be read.";

/** Why `restore` cannot be chosen; null when it can. */
export function reason(restore: Restore, code: Loaded, conversation: Loaded): string | null {
  switch (restore) {
    case "conversation":
      if (conversation == null) return FAILED;
      return conversation.can_rewind
        ? null
        : (conversation.error ?? "The conversation cannot be rewound to before this message.");
    case "code":
      if (code == null) return FAILED;
      if (!code.can_rewind)
        return code.error ?? "The files cannot be restored to before this message.";
      return changedCount(code) === 0 ? "Nothing to restore" : null;
    case "both":
      return reason("conversation", code, conversation) ?? reason("code", code, conversation);
  }
}

/** The first choice that can be done: both parts first for Rewind, as in Claude Code. */
export function firstChoice(purpose: Purpose, code: Loaded, conversation: Loaded): Restore | null {
  const order: Restore[] = purpose === "edit" ? ["conversation"] : ["both", "conversation", "code"];
  return order.find((restore) => reason(restore, code, conversation) === null) ?? null;
}

/** "2 files change: +12 -4", or that nothing changed since the message. */
export function summary(preview: RewindPreview): string {
  const count = changedCount(preview);
  if (count === 0) return "No files changed since this message.";
  const noun = count === 1 ? "1 file changes" : `${String(count)} files change`;
  return `${noun}: +${String(preview.insertions)} -${String(preview.deletions)}`;
}
