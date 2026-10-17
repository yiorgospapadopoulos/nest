import type { AgentMessage, NestEvent } from "../../api/types.ts";
import { buildTranscript, type TranscriptItem } from "../../transcript/build.ts";
import { agentReport } from "../../transcript/report.ts";
import { Markdown } from "../../ui/Markdown.tsx";
import { MessageItem, type MessageEntry } from "./Transcript.tsx";

const isMessage = (item: TranscriptItem): item is MessageEntry =>
  item.kind !== "approval" &&
  item.kind !== "pixie" &&
  item.kind !== "card" &&
  item.kind !== "artifact";

/** The messages as transcript rows: text, thinking, and tool calls with their results. */
function workItems(messages: AgentMessage[], root: string | null): MessageEntry[] {
  const events: NestEvent[] = messages.map((m) => ({
    id: m.event_id,
    type: "session.message",
    ts: m.ts,
    session_id: null,
    payload: { blocks: m.blocks, parent_tool_use_id: null },
  }));
  return buildTranscript(events, {}, root).filter(isMessage);
}

interface Props {
  prompt: string | null;
  messages: AgentMessage[];
  report: string | null;
  running: boolean;
  // The chat's folder, for showing paths relative to it.
  root: string | null;
}

/** One call's work, read only: what it was asked, its messages, then its report. */
export function WorkBody({ prompt, messages, report, running, root }: Props) {
  const items = workItems(messages, root);
  return (
    <div className="wk">
      {prompt !== null && (
        <div className="wk-sec">
          <h4>Asked</h4>
          <Markdown text={prompt} />
        </div>
      )}
      {items.length > 0 && (
        <div className="tx">
          {items.map((item) => (
            <MessageItem key={item.key} item={item} />
          ))}
        </div>
      )}
      {running ? (
        <p className="wk-run">
          <span className="spin" aria-hidden="true" />
          Working
        </p>
      ) : (
        report !== null && (
          <div className="wk-sec wk-rep">
            <h4>Report</h4>
            <Markdown text={agentReport(report)} />
          </div>
        )
      )}
    </div>
  );
}
