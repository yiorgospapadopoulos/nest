import { useLayoutEffect, useRef } from "react";
import type { TranscriptItem } from "../../transcript/build.ts";

/**
 * Sending goes to the latest, however far up the reader was (B122). Read from the chat, not
 * the composer: the Mac's composer is outside the page. A message sent during a turn shows
 * in the queue first, so a queue that grows is a send too.
 */
export function useJumpOnSend(
  items: TranscriptItem[],
  queued: number,
  loaded: boolean,
  jump: () => void,
): void {
  const last = items.findLast((item) => item.kind === "user");
  const message = last === undefined ? -1 : Number(last.key);
  // What a loading chat already holds was sent earlier.
  const seen = useRef<{ message: number; queued: number } | null>(null);
  useLayoutEffect(() => {
    if (!loaded) return;
    const was = seen.current;
    seen.current = { message, queued };
    if (was !== null && (message > was.message || queued > was.queued)) jump();
  }, [message, queued, loaded, jump]);
}
