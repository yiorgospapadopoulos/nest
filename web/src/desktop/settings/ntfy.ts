import { useEffect } from "react";
import type { NotificationSettings } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";

export type Ntfy = NotificationSettings["ntfy"];

/** Saves a change to ntfy on the daemon; a refused one goes back. */
export function useSaveNtfy(): ((change: Partial<Ntfy>) => void) | null {
  const { state, actions } = useStore();
  const rules = state.notifications;
  useEffect(() => {
    void actions.loadNotifications();
  }, [actions]);
  if (rules === null) return null;
  return (change) => {
    void actions.saveNotifications({ ...rules, ntfy: { ...rules.ntfy, ...change } }, rules);
  };
}

const TOPIC_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

/** 32 letters and digits, inside the daemon's rule (16 to 64 of `[A-Za-z0-9_-]`). */
function randomTopic(): string {
  // 62 * 4 = 248: bytes from 248 up are skipped, so every character is as likely.
  const topic: string[] = [];
  while (topic.length < 32) {
    for (const byte of crypto.getRandomValues(new Uint8Array(48))) {
      if (byte < 248 && topic.length < 32) topic.push(TOPIC_CHARACTERS.charAt(byte % 62));
    }
  }
  return topic.join("");
}

/** The change that turns ntfy on: with no topic yet, a random one, as the daemon needs one. */
export function turnOn(ntfy: Ntfy): Partial<Ntfy> {
  return (ntfy.topic ?? "") === "" ? { enabled: true, topic: randomTopic() } : { enabled: true };
}
