// What Claude Code wraps around a subagent's final report (B40 live check).
const HAND_BACK = "[Subagent hand-back]";
const REPORT_FOLLOWS = "The report follows:\n";
const AGENT_ID = /^agentId: .*$/m;
const USAGE = /<usage>[\s\S]*?<\/usage>\s*$/;

/**
 * An agent call's answer without Claude Code's wrapping: the hand-back frame, the agentId
 * line and what follows it, the usage block and the two-space indent of each report line.
 * The text as it came when nothing would be left.
 */
export function agentReport(text: string): string {
  let report = text;
  if (report.startsWith(HAND_BACK)) {
    const at = report.indexOf(REPORT_FOLLOWS);
    report = at === -1 ? "" : report.slice(at + REPORT_FOLLOWS.length);
  }
  const id = AGENT_ID.exec(report);
  if (id !== null) report = report.slice(0, id.index);
  report = report
    .replace(USAGE, "")
    .split("\n")
    .map((line) => (line.startsWith("  ") ? line.slice(2) : line))
    .join("\n")
    .trim();
  return report === "" ? text : report;
}
