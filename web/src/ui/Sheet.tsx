import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE = "button:not([tabindex='-1']):not(:disabled), input, textarea";

/**
 * Modal plumbing shared by sheets and action sheets: rendered over everything, focus moves
 * into it and returns where it came from, Escape and the scrim close it, Tab stays inside.
 */
function useModal(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    // At least the body; the element that opened the modal gets focus back.
    const opener = document.activeElement as HTMLElement;
    const box = ref.current;
    const first =
      box?.querySelector<HTMLElement>("[data-autofocus]") ??
      box?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus({ preventScroll: true });
    // A text field opens with its text selected, ready to be replaced.
    if (first instanceof HTMLInputElement) first.select();
    return () => {
      opener.focus({ preventScroll: true });
    };
  }, []);
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close.current();
      return;
    }
    if (event.key !== "Tab") return;
    const items = [...event.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE)];
    const index = items.indexOf(document.activeElement as HTMLElement);
    const target = event.shiftKey
      ? index <= 0
        ? items.at(-1)
        : null
      : index === items.length - 1
        ? items[0]
        : null;
    if (target) {
      event.preventDefault();
      target.focus();
    }
  };
  return { ref, onKeyDown };
}

function Scrim({ onClose }: { onClose: () => void }) {
  return <button className="scrim" aria-label="Close" tabIndex={-1} onClick={onClose} />;
}

interface SheetProps {
  title: string;
  onClose: () => void;
  full?: boolean;
  // Header buttons; by default a single "Done" on the right.
  leading?: ReactNode;
  trailing?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}

export function Sheet({ title, onClose, full, leading, trailing, footer, children }: SheetProps) {
  const id = useId();
  const { ref, onKeyDown } = useModal(onClose);
  return createPortal(
    <>
      <Scrim onClose={onClose} />
      <div
        ref={ref}
        className={full === true ? "sheet full gl" : "sheet gl"}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        onKeyDown={onKeyDown}
      >
        <div className="grab" aria-hidden="true" />
        <div className={leading === undefined ? "sh-h" : "sh-h mid"}>
          {leading}
          <h2 id={id}>{title}</h2>
          {trailing ?? (
            <button className="done" onClick={onClose}>
              Done
            </button>
          )}
        </div>
        <div className="sh-b">{children}</div>
        {footer !== undefined && <div className="sh-f">{footer}</div>}
      </div>
    </>,
    document.body,
  );
}

interface ActionSheetProps {
  label: string;
  title?: ReactNode;
  onClose: () => void;
  role?: "dialog" | "alertdialog";
  children: ReactNode;
}

/** An iOS style action sheet: a group of choices and a separate Cancel button. */
export function ActionSheet({
  label,
  title,
  onClose,
  role = "dialog",
  children,
}: ActionSheetProps) {
  const { ref, onKeyDown } = useModal(onClose);
  return createPortal(
    <>
      <Scrim onClose={onClose} />
      <div
        ref={ref}
        className="asheet"
        role={role}
        aria-modal="true"
        aria-label={label}
        onKeyDown={onKeyDown}
      >
        <div className="asg" role={role === "dialog" ? "menu" : undefined}>
          {title !== undefined && <div className="ast">{title}</div>}
          {children}
        </div>
        <div className="asg">
          {/* A confirmation opens on Cancel, so one stray Enter changes nothing. */}
          <button
            className="asi cxl"
            data-autofocus={role === "alertdialog" ? true : undefined}
            onClick={onClose}
          >
            Cancel
          </button>
        </div>
      </div>
    </>,
    document.body,
  );
}
