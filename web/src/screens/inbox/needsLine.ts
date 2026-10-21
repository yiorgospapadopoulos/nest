import { mergeOf, obj, planOf, questionsOf, reviewOf, str, toolArg } from "../../api/payloads.ts";
import type { Approval, StuckFlag, StuckReason } from "../../api/types.ts";

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
    case "permission": {
      const tool = str(approval.payload.tool) ?? "Tool";
      const arg = toolArg(obj(approval.payload.input), root);
      return { kind: "Permission", detail: `${tool} ${arg}`.trim() };
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

/** A chat that looks stuck, with the reason. */
export function stuckLine(stuck: StuckFlag): NeedsLine {
  return { kind: "Stuck", detail: STUCK_REASONS[stuck.reason] };
}
