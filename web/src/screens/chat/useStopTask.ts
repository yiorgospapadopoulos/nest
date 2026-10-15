import { createContext, useState } from "react";
import { useStore } from "../../store/context.ts";

/** Stops one background task or subagent of a chat (B59), apart from the composer's Stop. */
export interface Stopper {
  // Whether a running task offers a stop: not once the chat's run turned out closed.
  offered: (id: string) => boolean;
  // Sent and waiting for the task's end.
  stopping: (id: string) => boolean;
  stop: (id: string) => void;
}

type Mark = "stopping" | "hidden";

export function useStopTask(sessionId: string): Stopper {
  const { actions } = useStore();
  const [marks, setMarks] = useState<Readonly<Record<string, Mark>>>({});
  const mark = (id: string, value: Mark | null) => {
    setMarks((current) => {
      const rest = Object.fromEntries(Object.entries(current).filter(([key]) => key !== id));
      return value === null ? rest : { ...rest, [id]: value };
    });
  };
  return {
    offered: (id) => marks[id] !== "hidden",
    stopping: (id) => marks[id] === "stopping",
    stop: (id) => {
      mark(id, "stopping");
      void actions.stopTask(sessionId, id).then((outcome) => {
        // A finished task's row comes back from the refetch; a failed stop can be tried again.
        if (outcome === "closed") mark(id, "hidden");
        else if (outcome !== "sent") mark(id, null);
      });
    },
  };
}

/** What the rows of a chat's calls need beyond their item (B59). */
export interface CallControls {
  // Subagents' streaming text, by the id of their Agent call.
  agentLive: Readonly<Record<string, string>>;
  // Calls whose background task still runs.
  running: ReadonlySet<string>;
  // Null where nothing can be stopped, as in a read-only transcript.
  stopper: Stopper | null;
}

export const CallContext = createContext<CallControls>({
  agentLive: {},
  running: new Set(),
  stopper: null,
});
