import { useRef, useState } from "react";

/**
 * A value saved as soon as it changes and shown changed at once, so a quick second change
 * builds on the first. Once every save has settled the saved value shows again: what the
 * Mac kept, which puts a refused change back by itself.
 */
export function usePending<T>(
  saved: T,
  save: (next: T) => Promise<unknown>,
): [T, (next: T) => void] {
  // Boxed, as the value itself may be null.
  const [pending, setPending] = useState<{ value: T } | null>(null);
  const inFlight = useRef(0);
  const change = (next: T) => {
    setPending({ value: next });
    inFlight.current += 1;
    void save(next).then(() => {
      inFlight.current -= 1;
      if (inFlight.current === 0) setPending(null);
    });
  };
  return [pending === null ? saved : pending.value, change];
}
