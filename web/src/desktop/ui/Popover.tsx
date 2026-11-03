import {
  useId,
  useLayoutEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import {
  useDismiss,
  useMisdirectedPress,
  useNoTooltip,
  useOverlay,
  usePlaced,
  useRestoreFocus,
} from "./floating.ts";
import { anchored, type Align, type Box, type Side } from "./place.ts";

const FOCUSABLE =
  "button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select, [tabindex]:not([tabindex='-1'])";

interface Props {
  // What it opens from; read when it opens and whenever it renders.
  anchor: RefObject<HTMLElement | null>;
  label: string;
  onClose: () => void;
  side?: Side;
  align?: Align;
  className?: string;
  children: ReactNode;
}

function rect(element: HTMLElement | null): Box {
  const r = element?.getBoundingClientRect();
  return { left: r?.left ?? 0, top: r?.top ?? 0, width: r?.width ?? 0, height: r?.height ?? 0 };
}

/**
 * Content anchored to a control, as the Mac's .popover: below it (above when there is no
 * room), the first control focused, Tab kept inside, and Escape, Ctrl+W or a press
 * outside closes it; the press outside still reaches what it pressed. Render it while it
 * is open.
 */
export function Popover({
  anchor,
  label,
  onClose,
  side = "below",
  align = "center",
  className,
  children,
}: Props) {
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  useRestoreFocus();
  useNoTooltip(() => anchor.current);
  useMisdirectedPress(() => box.current);
  useOverlay(onClose);
  useDismiss({
    inside: (target) =>
      box.current?.contains(target) === true ||
      anchor.current?.contains(target) === true ||
      // A menu opened from inside the popover is part of it.
      (target instanceof Element && target.closest("[data-dk-menu]") !== null),
    onDismiss: onClose,
    swallow: false,
  });
  const style = usePlaced(box, (size, view) =>
    anchored(rect(anchor.current), size, view, side, align),
  );

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
    if (items.length === 0) {
      event.preventDefault();
      return;
    }
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
      ref={box}
      id={id}
      className={className === undefined ? "dk-pop" : `dk-pop ${className}`}
      role="dialog"
      aria-label={label}
      tabIndex={-1}
      style={style}
      onKeyDown={onKeyDown}
    >
      {children}
    </div>,
    document.body,
  );
}
