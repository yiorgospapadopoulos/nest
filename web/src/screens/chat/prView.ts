import type { ChecksState, PrStatus } from "../../api/types.ts";
import { prLabel } from "../../format.ts";
import type { Tone } from "../../store/selectors.ts";

const CHECKS: Record<ChecksState, { tone: Tone; text: string }> = {
  pending: { tone: "wait", text: "checks running" },
  success: { tone: "rev", text: "checks passed" },
  failure: { tone: "fail", text: "checks failed" },
  none: { tone: "idle", text: "no checks" },
};

/** The chat's pull request: its number and how its checks stand, with a tone for the dot. */
export function prView(
  pr: PrStatus | null,
  url: string,
): { label: string; tone: Tone; text: string } {
  const status =
    pr === null
      ? { tone: "idle" as const, text: "status not read yet" }
      : pr.state === "open"
        ? CHECKS[pr.checks.state]
        : { tone: "done" as const, text: pr.state };
  const label = pr === null ? prLabel(url) : `#${String(pr.number)}`;
  return { label, ...status };
}
