import { useLayoutEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useOverlay, useRestoreFocus } from "../ui/floating.ts";
import { Glyph } from "./glyphs.tsx";

const FOCUSABLE =
  "button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select, [tabindex]:not([tabindex='-1'])";

interface Props {
  title: string;
  onClose: () => void;
  width?: number;
  // The diff and image sheets take the window, inside a margin.
  large?: boolean;
  // Draws its own header and footer, as the diff sheet does.
  bare?: boolean;
  children: ReactNode;
}

/**
 * A sheet over the window, as the Mac's SheetFrame: a scrim, then the title with its close
 * button and the content on the sheet surface. Escape, Ctrl+W, a click on the scrim or
 * the close button closes it; Tab stays inside.
 */
export function Sheet({
  title,
  onClose,
  width = 580,
  large = false,
  bare = false,
  children,
}: Props) {
  const box = useRef<HTMLDivElement>(null);
  useRestoreFocus();
  useOverlay(onClose);

  useLayoutEffect(() => {
    const element = box.current;
    const target =
      element?.querySelector<HTMLElement>("[data-autofocus]") ??
      element?.querySelector<HTMLElement>(FOCUSABLE) ??
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
    if (items.length === 0) return;
    const index = items.indexOf(document.activeElement as HTMLElement);
    const wrap = event.shiftKey
      ? index <= 0
        ? items.at(-1)
        : null
      : index === items.length - 1
        ? items[0]
        : null;
    if (wrap != null) {
      event.preventDefault();
      wrap.focus();
    }
  };

  return createPortal(
    <div
      className={large ? "dc-scrim large" : "dc-scrim"}
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={box}
        className={large ? "dc-sheet large" : "dc-sheet"}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        style={large ? undefined : { width }}
        onKeyDown={onKeyDown}
      >
        {bare ? (
          children
        ) : (
          <>
            <div className="dc-sheet-h">
              <h2>{title}</h2>
              <button
                className="dk-btn k-plain icon"
                aria-label={`Close ${title.toLowerCase()}`}
                onClick={onClose}
              >
                <Glyph name="close" size={10} />
              </button>
            </div>
            <div className="dc-sheet-b">{children}</div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}
