import { useCallback, useEffect, useRef, useState } from "react";
import type { SetupCheck } from "../../api/types.ts";
import { useApi } from "../context.ts";

export interface Checks {
  // Null until the first answer; they can take several seconds.
  checks: SetupCheck[] | null;
  checking: boolean;
  refresh: () => void;
}

/** `GET /api/setup/checks`, asked at once and again each time the window regains the focus. */
export function useChecks(): Checks {
  const api = useApi();
  const [checks, setChecks] = useState<SetupCheck[] | null>(null);
  const [checking, setChecking] = useState(true);
  const latest = useRef(0);
  const ask = useCallback(() => {
    latest.current += 1;
    const asked = latest.current;
    api.setupChecks().then(
      (found) => {
        if (asked !== latest.current) return;
        setChecks(found.checks);
        setChecking(false);
      },
      () => {
        if (asked === latest.current) setChecking(false);
      },
    );
  }, [api]);
  const refresh = useCallback(() => {
    setChecking(true);
    ask();
  }, [ask]);
  useEffect(() => {
    ask();
    window.addEventListener("focus", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
    };
  }, [ask, refresh]);
  return { checks, checking, refresh };
}
