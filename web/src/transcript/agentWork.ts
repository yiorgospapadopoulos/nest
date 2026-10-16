import { list, str } from "../api/payloads.ts";
import type { AgentMessage, NestEvent } from "../api/types.ts";

/** The newest stored event among the messages; 0 for none. */
export function lastEvent(messages: AgentMessage[]): number {
  return Math.max(0, ...messages.map((m) => m.event_id));
}

/**
 * A subagent's messages that arrived after a snapshot (B46): the chat's stored events
 * whose parent is `parent` (its first Agent call, also when a SendMessage continued it),
 * newer than `after`.
 */
export function liveMessages(
  events: NestEvent[] | undefined,
  parent: string,
  after: number,
): AgentMessage[] {
  return (events ?? []).flatMap((e) =>
    e.type === "session.message" &&
    str(e.payload.parent_tool_use_id) === parent &&
    e.id !== null &&
    e.id > after
      ? [{ event_id: e.id, ts: e.ts, blocks: list(e.payload.blocks) }]
      : [],
  );
}
