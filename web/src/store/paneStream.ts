import type { NestEvent } from "../api/types.ts";

const STREAMS = new Set(["session.delta", "session.thinking_delta", "session.subagent_delta"]);

/** Streaming text of a chat other than `chat`. Only the chat on screen shows it. */
export function streamOfAnother(event: NestEvent, chat: string): boolean {
  return STREAMS.has(event.type) && event.session_id !== chat;
}
