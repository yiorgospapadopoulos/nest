import { useEffect, useSyncExternalStore } from "react";

function subscribe(onChange: () => void): () => void {
  document.addEventListener("visibilitychange", onChange);
  return () => {
    document.removeEventListener("visibilitychange", onChange);
  };
}

/** Whether the app is on screen; false while it is in the background or the phone locked. */
export function usePageVisible(): boolean {
  return useSyncExternalStore(subscribe, () => document.visibilityState === "visible");
}

/**
 * Marks the page while it is hidden (`data-hidden` on <html>), so the stylesheets pause
 * continuous animations such as the running pulse and the working shimmer.
 */
export function usePauseWhenHidden(): void {
  const visible = usePageVisible();
  useEffect(() => {
    document.documentElement.toggleAttribute("data-hidden", !visible);
  }, [visible]);
}
