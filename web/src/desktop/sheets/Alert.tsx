import { useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { Button, type ButtonKind } from "../ui/controls.tsx";
import { useOverlay, useRestoreFocus } from "../ui/floating.ts";
import "./sheets.css";

export interface AlertAction {
  title: string;
  kind?: ButtonKind;
  onSelect: () => void;
}

/**
 * The Mac's .alert and .confirmationDialog: a small centred box with the question, a line
 * under it and its buttons, Cancel first. Escape, Ctrl+W or Cancel closes it.
 */
export function Alert({
  title,
  message,
  actions,
  onClose,
}: {
  title: string;
  message: string;
  actions: AlertAction[];
  onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  useRestoreFocus();
  useOverlay(onClose);
  useLayoutEffect(() => {
    box.current?.querySelector<HTMLElement>("[data-default]")?.focus({ preventScroll: true });
  }, []);
  return createPortal(
    <div
      className="dks-alertscrim"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={box}
        className="dks-alert"
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }}
      >
        <h2>{title}</h2>
        {message !== "" && <p>{message}</p>}
        <div className="dks-alertb">
          <Button kind="soft" onClick={onClose}>
            Cancel
          </Button>
          {actions.map((action, index) => (
            <Button
              key={action.title}
              kind={action.kind ?? "primary"}
              data-default={index === actions.length - 1 ? true : undefined}
              onClick={() => {
                onClose();
                action.onSelect();
              }}
            >
              {action.title}
            </Button>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** A question with one action, red when it destroys something, as confirmationDialog. */
export function Confirm({
  title,
  message,
  action,
  destructive = false,
  onConfirm,
  onClose,
}: {
  title: string;
  message?: string;
  action: string;
  destructive?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Alert
      title={title}
      message={message ?? ""}
      actions={[
        { title: action, kind: destructive ? "destructive" : "primary", onSelect: onConfirm },
      ]}
      onClose={onClose}
    />
  );
}
