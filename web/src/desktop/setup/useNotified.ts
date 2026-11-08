import { useCallback, useState } from "react";

// A test notification that arrived, kept on this device: the daemon cannot see it, and the
// tick went away with every restart of the app (B136).
export const NOTIFIED_KEY = "nest.desktop.setup.notified";

function readNotified(): boolean {
  try {
    return localStorage.getItem(NOTIFIED_KEY) === "1";
  } catch {
    return false;
  }
}

/** Whether a test notification reached this device, and the call that records one. */
export function useNotified(): [boolean, () => void] {
  const [notified, setNotified] = useState(readNotified);
  const mark = useCallback(() => {
    try {
      localStorage.setItem(NOTIFIED_KEY, "1");
    } catch {
      // The tick then lasts until the app closes.
    }
    setNotified(true);
  }, []);
  return [notified, mark];
}
