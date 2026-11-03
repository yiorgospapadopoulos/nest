// What the reader shows about an artifact's pages (B88), as the phone reader reads it
// (screens/artifacts/ArtifactReader.tsx): what they stored, and their asks of Claude.
import { useCallback, useEffect, useState } from "react";
import type { ArtifactAnswer } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import type { AskCount } from "./text.ts";

/**
 * The size of what the artifact's pages stored, read when it opens and again after a
 * change made elsewhere; a write of the page shown sets it from the reply.
 */
export function useStoredSize(id: string) {
  const { actions } = useStore();
  const [stored, setStored] = useState<{ id: string; size: number } | null>(null);
  const [reads, setReads] = useState(0);
  useEffect(() => {
    let current = true;
    void actions.artifactStorage(id).then((found) => {
      if (current && found !== null) setStored({ id, size: found.size });
    });
    return () => {
      current = false;
    };
  }, [actions, id, reads]);
  const setSize = useCallback(
    (size: number) => {
      setStored({ id, size });
    },
    [id],
  );
  const reread = useCallback(() => {
    setReads((n) => n + 1);
  }, []);
  return { size: stored?.id === id ? stored.size : 0, setSize, reread };
}

// Asks a day when a reply or event lacks the limit: the default of [artifacts] ask_daily_limit.
const ASK_LIMIT = 20;

/**
 * Whether Claude is answering one of the artifact's pages, here or on another device (the
 * `artifact.ask` events), and today's count: read on opening when the pages have asked
 * today, then from each answer and finished ask.
 */
export function useAsks(id: string) {
  const { actions } = useStore();
  const [running, setRunning] = useState(0);
  const [elsewhere, setElsewhere] = useState(false);
  const [count, setCount] = useState<AskCount | null>(null);
  const counted = useCallback((remaining: unknown, limit: unknown) => {
    if (typeof remaining !== "number") return;
    setCount({ remaining, limit: typeof limit === "number" ? limit : ASK_LIMIT });
  }, []);
  useEffect(() => {
    let current = true;
    void actions.askStatus(id).then((status) => {
      if (current && status !== null && status.used > 0) counted(status.remaining, status.limit);
    });
    return () => {
      current = false;
    };
  }, [actions, id, counted]);
  useEffect(
    () =>
      actions.onEvent((event) => {
        const p = event.payload;
        if (event.type !== "artifact.ask" || p.artifact_id !== id) return;
        setElsewhere(p.state === "started");
        if (p.state === "finished") counted(p.remaining, p.limit);
      }),
    [actions, id, counted],
  );
  const local = useCallback(
    async (run: () => Promise<ArtifactAnswer>) => {
      setRunning((n) => n + 1);
      try {
        const answer = await run();
        counted(answer.remaining, answer.limit);
        return answer;
      } finally {
        setRunning((n) => n - 1);
      }
    },
    [counted],
  );
  return { asking: running > 0 || elsewhere, count, local };
}
