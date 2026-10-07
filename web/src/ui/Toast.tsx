import { useEffect } from "react";
import { useStore } from "../store/context.ts";
import { Icon } from "./Icon.tsx";

export const TOAST_MS = 3200;

export function Toast() {
  const { state, actions } = useStore();
  const toast = state.toast;

  useEffect(() => {
    if (toast === null) return;
    const timer = window.setTimeout(actions.dismissToast, TOAST_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [toast, actions]);

  return (
    <div role="status" aria-live="polite">
      {toast !== null && (
        <div key={toast.id} className={`toast gl gl2 ${toast.tone}`}>
          <Icon name={toast.tone === "error" ? "x" : toast.tone === "info" ? "bell" : "check"} />
          <span>{toast.text}</span>
        </div>
      )}
    </div>
  );
}
