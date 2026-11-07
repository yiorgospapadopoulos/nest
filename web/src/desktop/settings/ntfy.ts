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
