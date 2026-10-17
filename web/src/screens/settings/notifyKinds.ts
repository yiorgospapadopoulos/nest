import type { NotifyKind } from "../../api/types.ts";

// In the order the settings list them (design/ui-rules.json).
export const KINDS: { kind: NotifyKind; label: string }[] = [
  { kind: "needs_approval", label: "Approvals" },
  { kind: "question", label: "Questions" },
  { kind: "review_ready", label: "Work ready for review" },
  { kind: "failed", label: "Agent errors" },
  { kind: "finished", label: "Finished turns" },
  { kind: "ci_failed", label: "Pull request checks failed" },
  { kind: "ready_to_merge", label: "Pull requests ready to merge" },
  { kind: "stuck", label: "Chats that look stuck" },
  { kind: "pixie_report", label: "Pixie reports" },
  { kind: "usage_limit", label: "Usage limit pauses" },
];
