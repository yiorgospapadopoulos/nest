import { useEffect } from "react";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";

// How long a note shows, errors included (Shell.show).
export const DESKTOP_TOAST_MS = 3000;

/**
 * A short note under the tab strip, as the Mac's ToastView: centred, for 3 seconds
 * whatever its kind, and never in the way, since the pointer passes through it.
 */
export function DesktopToast() {
  const { state, actions } = useStore();
  const toast = state.toast;

  useEffect(() => {
    if (toast === null) return;
    const timer = window.setTimeout(actions.dismissToast, DESKTOP_TOAST_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [toast, actions]);

  return (
    <div className="dk-toasts" role="status" aria-live="polite">
      {toast !== null && (
        <div key={toast.id} className={`dk-toast ${toast.tone}`}>
          <Icon name={toast.tone === "error" ? "x" : toast.tone === "info" ? "bell" : "check"} />
          <span>{toast.text}</span>
        </div>
      )}
    </div>
  );
}
