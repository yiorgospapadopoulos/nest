import { useLayoutEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon } from "../../ui/Icon.tsx";
import { Button } from "../ui/controls.tsx";
import { useOverlay, useRestoreFocus } from "../ui/floating.ts";
import "./sheets.css";

const FOCUSABLE =
  "button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select, [tabindex]:not([tabindex='-1'])";

interface Props {
  title: string;
  onClose: () => void;
  // In pixels, as SheetFrame's width (580) and maxHeight (700).
  width?: number;
  maxHeight?: number;
  // Buttons under the content, such as Cancel and Save, at the trailing edge.
  footer?: ReactNode;
  children: ReactNode;
}

/**
 * A centred sheet over a scrim, as the Mac's SheetFrame (OverlayLayer.swift): its title
 * and a close button, then scrolling content. Escape, Ctrl+W or a press on the scrim
 * closes it; Tab stays inside. Only where the Mac draws a sheet.
 */
export function SheetFrame({
  title,
  onClose,
  width = 580,
  maxHeight = 700,
  footer,
  children,
}: Props) {
  const box = useRef<HTMLDivElement>(null);
  useRestoreFocus();
  useOverlay(onClose);

  useLayoutEffect(() => {
    const element = box.current;
    const target =
      element?.querySelector<HTMLElement>("[data-autofocus]") ??
      element?.querySelector<HTMLElement>(
        ".dkh-body :is(input:not(:disabled), textarea:not(:disabled))",
      ) ??
      element;
    target?.focus({ preventScroll: true });
  }, []);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const items = [...event.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE)];
    const index = items.indexOf(document.activeElement as HTMLElement);
    const next = event.shiftKey
      ? index <= 0
        ? items.at(-1)
        : null
      : index === items.length - 1
        ? items[0]
        : null;
    if (next != null) {
      event.preventDefault();
      next.focus();
    }
  };

  return createPortal(
    <div
      className="dkh-scrim"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={box}
        className="dkh"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        style={{ width, maxHeight }}
        onKeyDown={onKeyDown}
      >
        <header className="dkh-head">
          <h2>{title}</h2>
          <Button
            kind="plain"
            iconOnly
            aria-label={`Close ${title.toLowerCase()}`}
            onClick={onClose}
          >
            <Icon name="x" />
          </Button>
        </header>
        <div className="dkh-body">{children}</div>
        {footer !== undefined && <footer className="dkh-foot">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}

/** A small grey label of a sheet's section, over its rows, as SheetSection. */
export function SheetSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="dkh-sec">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

/** A label on the left and a control on the right, a hairline between rows, as SheetRow. */
export function SheetRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="dkh-row">
      <span>{label}</span>
      <span className="dkh-ctl">{children}</span>
    </div>
  );
}
