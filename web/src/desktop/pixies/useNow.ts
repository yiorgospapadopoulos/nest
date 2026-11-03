import { useEffect, useState } from "react";

/** The time now, again every `ms`, for times written relative to today. */
export function useNow(ms = 60_000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(new Date());
    }, ms);
    return () => {
      window.clearInterval(timer);
    };
  }, [ms]);
  return now;
}
