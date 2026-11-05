// How both clients read what Autopilot decided (B120): the line in the chat and in the report.
import { list, obj, str } from "../api/payloads.ts";
import type { AutopilotDecision, AutopilotEnd, AutopilotReport, JsonValue } from "../api/types.ts";

const KINDS: ReadonlySet<unknown> = new Set<AutopilotDecision["kind"]>([
  "question",
  "plan",
  "allowed",
  "denied",
]);

/** A decision from its event; null for a malformed one. */
export function decisionOf(value: JsonValue | undefined): AutopilotDecision | null {
  const p = obj(value);
  const title = str(p.title);
  const answer = str(p.answer);
  if (!KINDS.has(p.kind) || title === null || answer === null) return null;
  return {
    kind: p.kind as AutopilotDecision["kind"],
    title,
    answer,
    at: str(p.at) ?? "",
    options: list(p.options)
      .map(obj)
      .map((option) => ({
        label: str(option.label) ?? "",
        description: str(option.description),
        picked: option.picked === true,
      })),
    reason: str(p.reason),
    detail: str(p.detail),
  };
}

const ENDINGS: ReadonlySet<unknown> = new Set<AutopilotEnd>([
  "done",
  "time",
  "weekly_cap",
  "stuck",
  "errors",
  "stopped",
  "off",
]);

/** A report from its event; null for a malformed one. */
export function reportOf(value: JsonValue | undefined): AutopilotReport | null {
  const p = obj(value);
  if (!ENDINGS.has(p.ended)) return null;
  return {
    started_at: str(p.started_at) ?? "",
    ended_at: str(p.ended_at) ?? "",
    ended: p.ended as AutopilotEnd,
    summary: str(p.summary),
    turns: typeof p.turns === "number" ? p.turns : 0,
    decisions: list(p.decisions)
      .map(decisionOf)
      .filter((decision) => decision !== null),
  };
}

/** What the line shows after the title. */
export function decisionAnswer(decision: AutopilotDecision): string {
  return decision.kind === "denied" ? "Denied" : decision.answer;
}

/** Why it went this way; a denied call stored before `reason` said so in its answer. */
export function decisionReason(decision: AutopilotDecision): string | null {
  return decision.reason ?? (decision.kind === "denied" ? decision.answer : null);
}

/** Whether the line has anything to open to. */
export function decisionOpens(decision: AutopilotDecision): boolean {
  return (
    decision.options.length > 0 || decision.detail !== null || decisionReason(decision) !== null
  );
}
