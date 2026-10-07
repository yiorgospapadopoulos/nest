import type { ChecksState, Session } from "../../api/types.ts";
import type { Tone } from "../../store/selectors.ts";
import { prLabel } from "../../format.ts";
import { Dot } from "../../ui/bits.tsx";

const CHECKS: Record<ChecksState, { tone: Tone; text: string }> = {
  pending: { tone: "wait", text: "checks running" },
  success: { tone: "rev", text: "checks passed" },
  failure: { tone: "fail", text: "checks failed" },
  none: { tone: "idle", text: "no checks" },
};

/** The chat's pull request with a dot for its checks; opens it on GitHub. */
export function PrChip({ session }: { session: Session }) {
  if (session.pr_url === null) return null;
  const pr = session.pr;
  const status =
    pr === null
      ? { tone: "idle" as const, text: "status not read yet" }
      : pr.state === "open"
        ? CHECKS[pr.checks.state]
        : { tone: "done" as const, text: pr.state };
  const label = pr === null ? prLabel(session.pr_url) : `#${String(pr.number)}`;
  return (
    <a
      className="chip prchip"
      href={pr?.url ?? session.pr_url}
      target="_blank"
      rel="noreferrer"
      aria-label={`Pull request ${label}, ${status.text}`}
    >
      <Dot tone={status.tone} />
      <span>{label}</span>
    </a>
  );
}
