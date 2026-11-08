import {
  mergeOf,
  obj,
  pixieCallOf,
  planOf,
  questionsOf,
  reviewCommentsDetail,
  reviewOf,
  str,
  toolCall,
} from "../../api/payloads.ts";
import type { Approval, GroupEntry, Pixie, StuckFlag, StuckReason } from "../../api/types.ts";

/** What needs the user, in the one grey line under a Needs you row (B77, NestKit's NeedsYouLine). */
export interface NeedsLine {
  kind: string;
  detail: string | null;
}

/** "Kind · detail", or the kind alone. */
export function lineText({ kind, detail }: NeedsLine): string {
  return detail === null ? kind : `${kind} · ${detail}`;
}

/** A plan's first line with text, without its Markdown heading marks. */
function firstLine(markdown: string): string | null {
  for (const line of markdown.split("\n")) {
    const text = line.replace(/^#+/, "").trim();
    if (text !== "") return text;
  }
  return null;
}

/** An approval's line; `root` shortens paths inside the chat's folder. */
export function approvalLine(approval: Approval, root: string | null): NeedsLine {
  switch (approval.kind) {
    case "question":
      return { kind: "Question", detail: questionsOf(approval)[0]?.question ?? null };
    case "review": {
      const { additions, deletions, files } = reviewOf(approval);
      const noun = files === 1 ? "file" : "files";
      return {
        kind: "Ready for review",
        detail: `+${String(additions)} -${String(deletions)} in ${String(files)} ${noun}`,
      };
    }
    case "plan":
      return { kind: "Plan", detail: firstLine(planOf(approval)) };
    case "merge": {
      const { number, title } = mergeOf(approval);
      return { kind: "Ready to merge", detail: `#${String(number)} ${title}` };
    }
    case "review_comments":
      return { kind: "Review comments", detail: reviewCommentsDetail(approval) };
    case "permission": {
      const tool = str(approval.payload.tool) ?? "Tool";
      return { kind: "Permission", detail: toolCall(tool, obj(approval.payload.input), root) };
    }
  }
}

/** A chat whose pull request failed its checks, naming them. */
export function checksFailedLine(names: string[]): NeedsLine {
  return { kind: "Checks failed", detail: names.length === 0 ? null : names.join(", ") };
}

const STUCK_REASONS: Record<StuckReason, string> = {
  waiting: "Waiting too long",
  silent: "No new output",
  repeating: "Repeating a call",
  long_turn: "Very long turn",
};

/**
 * The pixie an approval was raised by inside a pixie call (B114): the call of `agent`, the
 * member's own, else the group slot's `call`, among the chat's pixie calls. Null outside a
 * call or when the chat's calls do not name it.
 */
export function approvalPixie(
  approval: Approval,
  groups: GroupEntry[] | undefined,
  pixies: Record<string, Pixie>,
): Pixie | null {
  const ref = pixieCallOf(approval);
  if (ref === null || groups === undefined) return null;
  const calls = groups.flatMap((entry) => entry.calls);
  const call =
    calls.find((c) => c.tool_use_id === ref.agent) ?? calls.find((c) => c.tool_use_id === ref.call);
  return call === undefined ? null : (pixies[call.pixie_id] ?? null);
}

/** A chat that looks stuck, with the reason. */
export function stuckLine(stuck: StuckFlag): NeedsLine {
  return { kind: "Stuck", detail: STUCK_REASONS[stuck.reason] };
}
