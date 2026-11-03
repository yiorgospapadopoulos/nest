// A pull request's chip and popover words, as NestKit's PRBadge.
import type { PrStatus } from "../../../api/types.ts";
import type { Tone } from "../../../store/selectors.ts";

/**
 * The chip's dot, as NestKit's PRBadge.dot: amber while checks run, green when they passed,
 * red when one failed, hollow without checks; grey once merged or closed.
 */
export function prDot(pr: PrStatus): { tone: Tone; hollow: boolean } {
  if (pr.state !== "open") return { tone: "done", hollow: false };
  switch (pr.checks.state) {
    case "pending":
      return { tone: "wait", hollow: false };
    case "success":
      return { tone: "rev", hollow: false };
    case "failure":
      return { tone: "fail", hollow: false };
    case "none":
      return { tone: "done", hollow: true };
  }
}

/** "2 failed, 1 running, 3 passed", as PRBadge.checksSummary. */
export function checksSummary(checks: PrStatus["checks"]): string {
  const parts = [
    checks.failed > 0 ? `${String(checks.failed)} failed` : null,
    checks.pending > 0 ? `${String(checks.pending)} running` : null,
    checks.passed > 0 ? `${String(checks.passed)} passed` : null,
  ].filter((part) => part !== null);
  return parts.length === 0 ? "No checks" : parts.join(", ");
}
