import { useCallback, useEffect, useRef, useState } from "react";
import { useBridge } from "../context.ts";
import {
  RetryLoop,
  startService as start,
  type Connection,
  type ServiceState,
} from "../layout/connection.ts";

const windowTimers = {
  set: (callback: () => void, ms: number) => window.setTimeout(callback, ms),
  clear: (id: number) => {
    window.clearTimeout(id);
  },
};

// systemctl returns before the daemon listens; it gets a moment, as on the Mac.
const SETTLE_MS = 1500;
// Lost again this soon after it was reached: the backoff goes on rather than starting over.
const RELAPSE_MS = 10_000;

const CONNECTED: Connection = { kind: "connected" };
const IDLE: ServiceState = { kind: "idle" };

export interface Reconnect {
  connection: Connection;
  service: ServiceState;
  retry: () => void;
  startService: () => void;
}

/**
 * While `active`, tries `attempt` with the Mac's backoff until it succeeds (the daemon
 * answers); Start Nest service starts the user service, then tries again.
 */
export function useReconnect(active: boolean, attempt: () => Promise<boolean>): Reconnect {
  const bridge = useBridge();
  const [connection, setConnection] = useState<Connection>({ kind: "connecting" });
  const [service, setService] = useState<ServiceState>(IDLE);
  const latest = useRef(attempt);
  const loop = useRef<RetryLoop | null>(null);
  const reached = useRef({ at: 0, relapses: 0 });
  useEffect(() => {
    latest.current = attempt;
  });
  useEffect(() => {
    if (!active) return;
    const last = reached.current;
    const relapses = Date.now() - last.at < RELAPSE_MS ? last.relapses + 1 : 0;
    const running = new RetryLoop(
      () => latest.current(),
      (next) => {
        setConnection(next);
        if (next.kind !== "connected") return;
        setService(IDLE);
        reached.current = { at: Date.now(), relapses };
      },
      windowTimers,
      relapses,
    );
    loop.current = running;
    running.start();
    return () => {
      running.stop();
      if (loop.current === running) loop.current = null;
      // The next time it is needed starts afresh, as the Mac's service.reset().
      setConnection({ kind: "connecting" });
      setService(IDLE);
    };
  }, [active]);
  const retry = useCallback(() => {
    loop.current?.retry();
  }, []);
  const startService = useCallback(() => {
    setService({ kind: "starting" });
    void start(() => bridge.startService()).then((state) => {
      setService(state);
      if (state.kind === "started") window.setTimeout(retry, SETTLE_MS);
    });
  }, [bridge, retry]);
  return active
    ? { connection, service, retry, startService }
    : { connection: CONNECTED, service: IDLE, retry, startService };
}
