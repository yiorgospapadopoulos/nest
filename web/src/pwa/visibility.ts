/**
 * Tells the daemon whether Nest is on screen, so it refreshes the usage numbers only
 * while someone can see them (D031). A report lapses on the daemon after 150 s.
 */

export const HEARTBEAT_MS = 60_000;

export interface VisibilityEnv {
  document: Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">;
  report: (visible: boolean) => Promise<unknown>;
}

/** Reports now, on every visibility change and every minute while visible; returns a stop. */
export function reportVisibility({ document, report }: VisibilityEnv): () => void {
  let heartbeat: ReturnType<typeof setInterval> | undefined;

  const send = (visible: boolean) => {
    // A missed report only delays a refresh; the next heartbeat tries again.
    report(visible).catch(() => undefined);
  };

  const update = () => {
    const visible = document.visibilityState === "visible";
    clearInterval(heartbeat);
    heartbeat = visible
      ? setInterval(() => {
          send(true);
        }, HEARTBEAT_MS)
      : undefined;
    send(visible);
  };

  update();
  document.addEventListener("visibilitychange", update);
  return () => {
    document.removeEventListener("visibilitychange", update);
    clearInterval(heartbeat);
    send(false);
  };
}
