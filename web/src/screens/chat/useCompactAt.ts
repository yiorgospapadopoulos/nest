import type { Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { supportsFeature } from "../../store/selectors.ts";
import { compactAtChoice } from "./options.ts";

export interface CompactAtControl {
  // Null: the engine's own.
  value: number | null;
  pick: (size: number | null) => void;
}

/**
 * A chat's size to compact at (B146), or null on an engine that compacts its own way. A
 * pixie's own chat changes through its pixie, as its model and effort do; a habit run's or
 * a call's chat is its own.
 */
export function useCompactAt(session: Session | undefined): CompactAtControl | null {
  const { state, actions } = useStore();
  if (session === undefined || !supportsFeature(state, "compact_window", session.provider)) {
    return null;
  }
  const owner = session.pixie_id === null ? undefined : state.pixies[session.pixie_id];
  const pixie = owner?.chat_session_id === session.id ? owner : undefined;
  return {
    value: pixie === undefined ? session.compact_at : pixie.compact_at,
    pick: (size) => {
      const body = { compact_at: compactAtChoice(size) };
      if (pixie === undefined) void actions.update(session.id, body);
      else void actions.updatePixie(pixie.id, body);
    },
  };
}
