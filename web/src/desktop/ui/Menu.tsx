import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
  type Ref,
} from "react";
import { createPortal } from "react-dom";
import {
  elementAt,
  misdirected,
  swallowNextClick,
  useDismiss,
  useNoTooltip,
  useOverlay,
  usePlaced,
  useRestoreFocus,
} from "./floating.ts";
import { MenuIcon } from "./menuIcons.tsx";
import { first, last, step, typeahead, type MenuEntry } from "./menuItems.ts";
import { anchored, atPoint, type Align, type Box, type Side } from "./place.ts";

// Typed letters run together this long for typeahead.
const TYPEAHEAD_MS = 700;

// How far the pointer moves from the press that opened a menu before its release counts.
const PRESS_SLOP = 4;

/**
 * The press that opened a menu, until its release. Its release over an item chooses it
 * only once the pointer has moved since the press, as in an AppKit menu: a quick click
 * leaves the menu open even when it opened with an item under the pointer (moved to fit).
 */
export interface MenuPress {
  x: number;
  y: number;
  moved: boolean;
}

export interface Pressing {
  current: MenuPress | null;
}

export type Where =
  | { anchor: Box; side: Side; align: Align; minWidth?: number }
  | { point: { x: number; y: number } };

interface PanelProps {
  entries: MenuEntry[];
  label: string;
  where: Where;
  // Closes the whole menu; `select` runs after it closed.
  onClose: () => void;
  // The menu's own elements, for its outside press.
  tree: string;
  // Highlight the first item, as when opened from the keyboard.
  highlightFirst: boolean;
  // From the press that opened the menu until its release (MenuPress).
  pressing: Pressing;
  // A submenu: back to its parent (Left arrow, Escape).
  onBack?: () => void;
  // A submenu opened by the pointer does not take the keyboard until the pointer enters.
  takeFocus: boolean;
}

function box(element: Element): Box {
  const r = element.getBoundingClientRect();
  return { left: r.left, top: r.top, width: r.width, height: r.height };
}

/** One open menu list; a submenu is another, beside its row. */
function MenuPanel({
  entries,
  label,
  where,
  onClose,
  tree,
  highlightFirst,
  pressing,
  onBack,
  takeFocus,
}: PanelProps) {
  const id = useId();
  const panel = useRef<HTMLDivElement>(null);
  const rows = useRef<(HTMLDivElement | null)[]>([]);
  const [active, setActive] = useState(() => (highlightFirst ? first(entries) : -1));
  const [sub, setSub] = useState<{ index: number; keyboard: boolean; row: Box } | null>(null);
  const typed = useRef({ text: "", at: 0 });
  // The row a press on this menu began on.
  const pressedRow = useRef<number | null>(null);
  const chosen = useRef(false);
  const style: CSSProperties = usePlaced(panel, (size, view) => {
    if ("point" in where) return atPoint(where.point, size, view);
    return anchored(where.anchor, size, view, where.side, where.align);
  });
  const minWidth = "anchor" in where ? where.minWidth : undefined;

  useLayoutEffect(() => {
    if (takeFocus) panel.current?.focus({ preventScroll: true });
  }, [takeFocus]);

  const focusSelf = () => {
    panel.current?.focus({ preventScroll: true });
  };

  const choose = (index: number, keyboard: boolean) => {
    const entry = entries[index];
    if (entry === undefined) return;
    if (entry.type === "submenu") {
      const row = rows.current[index];
      if (entry.disabled !== true && row != null) setSub({ index, keyboard, row: box(row) });
      return;
    }
    if (entry.type !== undefined && entry.type !== "item") return;
    if (entry.disabled === true || chosen.current) return;
    // Once: the release chose it, so the click that may follow does nothing.
    chosen.current = true;
    onClose();
    entry.onSelect();
  };

  /*
   * A press and release on a row choose it, read on the window before anything else sees
   * them: a release after moving from the press that opened the menu, or a click's own
   * press and release. Neither waits for the click event, which WebKitGTK does not always
   * send, nor for React's handlers of the tree the menu was opened from, nor for other
   * listeners that may stop the press on its way down.
   */
  const latestChoose = useRef<(index: number) => void>(() => undefined);
  useLayoutEffect(() => {
    latestChoose.current = (index) => {
      if (entries[index]?.type !== "submenu") choose(index, false);
    };
  });
  useEffect(() => {
    const element = panel.current;
    if (element === null) return;
    // The row under the event by its position (elementAt), not the element it was sent to.
    const rowAt = (event: globalThis.PointerEvent): number | null => {
      const row = elementAt(event)?.closest("[data-dk-row]") ?? null;
      if (row === null || !element.contains(row) || row.closest(".dk-menu") !== element) {
        return null;
      }
      return Number(row.getAttribute("data-dk-row"));
    };
    // A press on a row sent elsewhere (the menu's own button) goes no further: there it
    // would close the menu, and its click would follow it.
    const keep = (event: globalThis.PointerEvent) => {
      if (!misdirected(event)) return;
      event.preventDefault();
      event.stopPropagation();
      if (event.type === "pointerup") swallowNextClick();
    };
    const down = (event: globalThis.PointerEvent) => {
      pressedRow.current = event.button === 0 ? rowAt(event) : null;
      if (pressedRow.current !== null) keep(event);
    };
    const up = (event: globalThis.PointerEvent) => {
      const index = rowAt(event);
      const clicked = index !== null && pressedRow.current === index;
      pressedRow.current = null;
      const dragged = pressing.current?.moved === true;
      if (index === null || event.button === 1 || !(clicked || dragged)) return;
      keep(event);
      latestChoose.current(index);
    };
    window.addEventListener("pointerdown", down, true);
    window.addEventListener("pointerup", up, true);
    return () => {
      window.removeEventListener("pointerdown", down, true);
      window.removeEventListener("pointerup", up, true);
    };
  }, [pressing]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // Shortcuts with Ctrl (Ctrl+W closes the menu first) belong to the window.
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    let handled = true;
    switch (event.key) {
      case "ArrowDown":
        setActive((a) => step(entries, a, 1));
        break;
      case "ArrowUp":
        setActive((a) => step(entries, a, -1));
        break;
      case "Home":
        setActive(first(entries));
        break;
      case "End":
        setActive(last(entries));
        break;
      case "Enter":
      case " ":
        if (active !== -1) choose(active, true);
        break;
      case "ArrowRight":
        if (entries[active]?.type === "submenu") choose(active, true);
        break;
      case "ArrowLeft":
        if (onBack !== undefined) onBack();
        break;
      case "Escape":
        if (onBack !== undefined) onBack();
        else onClose();
        break;
      case "Tab":
        onClose();
        break;
      default:
        if (event.key.length === 1) {
          const now = event.timeStamp;
          const text =
            now - typed.current.at < TYPEAHEAD_MS ? typed.current.text + event.key : event.key;
          typed.current = { text, at: now };
          setActive((a) => typeahead(entries, a, text));
        } else handled = false;
    }
    if (handled) {
      event.preventDefault();
      event.stopPropagation();
    }
  };

  const subEntry = sub === null ? undefined : entries[sub.index];
  // As AppKit's menus: once any item has a symbol, every title starts after the symbols.
  const iconed = entries.some(
    (entry) =>
      (entry.type === undefined || entry.type === "item" || entry.type === "submenu") &&
      entry.icon !== undefined,
  );

  return createPortal(
    <div
      ref={panel}
      className="dk-menu"
      role="menu"
      aria-label={label}
      tabIndex={-1}
      data-dk-menu={tree}
      aria-activedescendant={active === -1 ? undefined : `${id}-${String(active)}`}
      style={{ ...style, ...(minWidth === undefined ? {} : { minWidth }) }}
      onKeyDown={onKeyDown}
      onPointerEnter={() => {
        if (!takeFocus && onBack !== undefined) focusSelf();
      }}
      onContextMenu={(event) => {
        event.preventDefault();
      }}
    >
      {entries.map((entry, index) => {
        if (entry.type === "separator") {
          return <div key={index} className="dk-msep" role="separator" />;
        }
        if (entry.type === "section") {
          return (
            <div key={index} className="dk-mhead" role="presentation">
              {entry.title}
            </div>
          );
        }
        if (entry.type === "note") {
          return (
            <div key={index} className="dk-mnote" role="presentation">
              {entry.text}
            </div>
          );
        }
        const submenu = entry.type === "submenu";
        const item = submenu ? null : entry;
        const disabled = entry.disabled === true;
        const on = index === active;
        const checkable = item?.checked !== undefined;
        return (
          <div
            key={index}
            ref={(element) => {
              rows.current[index] = element;
            }}
            id={`${id}-${String(index)}`}
            className={`dk-mi${on ? " on" : ""}${item?.danger === true ? " danger" : ""}`}
            role={checkable ? "menuitemcheckbox" : "menuitem"}
            aria-label={entry.title}
            aria-checked={checkable ? item.checked === true : undefined}
            aria-disabled={disabled || undefined}
            aria-haspopup={submenu ? "menu" : undefined}
            aria-expanded={submenu ? sub?.index === index : undefined}
            onPointerMove={() => {
              if (active === index) return;
              setActive(disabled ? -1 : index);
              if (sub !== null && sub.index !== index) {
                setSub(null);
                focusSelf();
              }
              if (submenu && !disabled) choose(index, false);
            }}
            onPointerLeave={() => {
              if (sub?.index !== index) setActive(-1);
            }}
            data-dk-row={index}
            onClick={(event: MouseEvent) => {
              event.stopPropagation();
              choose(index, false);
            }}
          >
            <span className="dk-mcheck" aria-hidden="true">
              {item?.checked === true && (
                <svg viewBox="0 0 12 12">
                  <path d="M2.5 6.4l2.3 2.3L9.6 3.5" />
                </svg>
              )}
            </span>
            {iconed && (
              <span className="dk-micon" aria-hidden="true">
                {entry.icon !== undefined && <MenuIcon name={entry.icon} />}
              </span>
            )}
            <span className="dk-mtext">
              <span className="dk-mtitle">{entry.title}</span>
              {item?.detail !== undefined && item.detail !== "" && (
                <span className={item.warns === true ? "dk-mdetail warns" : "dk-mdetail"}>
                  {item.detail}
                </span>
              )}
            </span>
            {item?.shortcut !== undefined && <span className="dk-mkey">{item.shortcut}</span>}
            {submenu && (
              <svg className="dk-msub" viewBox="0 0 12 12" aria-hidden="true">
                <path d="M4.5 2.5L8 6l-3.5 3.5" />
              </svg>
            )}
          </div>
        );
      })}
      {subEntry?.type === "submenu" && sub !== null && (
        <MenuPanel
          key={`${String(sub.index)} ${String(sub.keyboard)}`}
          entries={subEntry.items}
          label={subEntry.title}
          where={{ anchor: sub.row, side: "right", align: "start" }}
          onClose={onClose}
          tree={tree}
          highlightFirst={sub.keyboard}
          pressing={pressing}
          takeFocus={sub.keyboard}
          onBack={() => {
            setSub(null);
            focusSelf();
          }}
        />
      )}
    </div>,
    document.body,
  );
}

export interface RootProps {
  entries: MenuEntry[];
  label: string;
  where: Where;
  onClose: () => void;
  highlightFirst: boolean;
  pressing: Pressing;
  // Presses on it do not count as outside, so it can toggle the menu itself.
  trigger?: () => HTMLElement | null;
}

/** An open menu with its dismissal, focus return and place in the overlay order. */
export function OpenMenu({
  entries,
  label,
  where,
  onClose,
  highlightFirst,
  pressing,
  trigger,
}: RootProps) {
  const tree = useId();
  useRestoreFocus();
  useNoTooltip(() => trigger?.());
  useOverlay(onClose);
  useDismiss({
    inside: (target) =>
      (target instanceof Element && target.closest(`[data-dk-menu="${tree}"]`) !== null) ||
      trigger?.()?.contains(target) === true,
    onDismiss: onClose,
    swallow: true,
  });
  useLayoutEffect(() => {
    // The press ends wherever it is released; a release on no item leaves the menu open.
    const release = () => {
      pressing.current = null;
    };
    const move = (event: globalThis.PointerEvent) => {
      const press = pressing.current;
      if (press === null || press.moved) return;
      press.moved = Math.hypot(event.clientX - press.x, event.clientY - press.y) > PRESS_SLOP;
    };
    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);
    return () => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointercancel", release);
    };
  }, [pressing]);
  return (
    <MenuPanel
      entries={entries}
      label={label}
      where={where}
      onClose={onClose}
      tree={tree}
      highlightFirst={highlightFirst}
      pressing={pressing}
      takeFocus
    />
  );
}

export interface TriggerProps {
  ref: Ref<HTMLButtonElement>;
  "aria-haspopup": "menu";
  "aria-expanded": boolean;
  onPointerDown: (event: PointerEvent<HTMLButtonElement>) => void;
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
}

interface MenuProps {
  // The menu's name for assistive technology.
  label: string;
  // Read when the menu opens, so it lists what is true then.
  items: MenuEntry[] | (() => MenuEntry[]);
  side?: Side;
  align?: Align;
  // Draws the button; spread the props onto it.
  children: (trigger: TriggerProps, open: boolean) => ReactNode;
  onOpenChange?: (open: boolean) => void;
}

/**
 * A menu opened from a button, below it (above when there is no room), as the Mac's Menu
 * and QuietMenu: a press opens it and a release on an item chooses; a click leaves it
 * open. Arrows, Home, End and typed letters move the highlight, Enter or Space chooses,
 * Right and Left open and close a submenu, Escape, Tab, a press outside or Ctrl+W close it.
 */
export function Menu({
  label,
  items,
  side = "below",
  align = "start",
  children,
  onOpenChange,
}: MenuProps) {
  const button = useRef<HTMLButtonElement | null>(null);
  const pressing = useRef<MenuPress | null>(null);
  const [open, setOpen] = useState<{
    entries: MenuEntry[];
    keyboard: boolean;
    anchor: Box;
    width: number;
  } | null>(null);
  const show = (keyboard: boolean) => {
    const element = button.current;
    if (element === null) return;
    setOpen({
      entries: typeof items === "function" ? items() : items,
      keyboard,
      anchor: box(element),
      width: element.offsetWidth,
    });
    onOpenChange?.(true);
  };
  const close = () => {
    setOpen(null);
    onOpenChange?.(false);
  };
  const trigger: TriggerProps = {
    ref: button,
    "aria-haspopup": "menu",
    "aria-expanded": open !== null,
    onPointerDown: (event) => {
      if (event.button !== 0 || event.ctrlKey) return;
      // Kept from taking the focus, which the open menu has.
      event.preventDefault();
      if (open !== null) {
        close();
        return;
      }
      pressing.current = { x: event.clientX, y: event.clientY, moved: false };
      show(false);
    },
    onClick: (event) => {
      // Enter or Space on the button; a pointer press already acted.
      if (event.detail !== 0) return;
      if (open !== null) close();
      else show(true);
    },
    onKeyDown: (event) => {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      if (open === null) show(true);
    },
  };
  return (
    <>
      {children(trigger, open !== null)}
      {open !== null && (
        <OpenMenu
          entries={open.entries}
          label={label}
          where={{ anchor: open.anchor, side, align, minWidth: open.width }}
          onClose={close}
          highlightFirst={open.keyboard}
          pressing={pressing}
          trigger={() => button.current}
        />
      )}
    </>
  );
}

interface QuietMenuProps {
  title: string;
  // What the menu chooses, its tooltip and the first part of its name.
  help: string;
  items: MenuEntry[] | (() => MenuEntry[]);
  // A colour in place of the greys, such as the wait colour for Bypass.
  tint?: string;
  chevron?: boolean;
  align?: Align;
  className?: string;
}

/** The Mac's QuietMenu: a selector that reads as plain text, highlights on hover, opens a list. */
export function QuietMenu({
  title,
  help,
  items,
  tint,
  chevron = false,
  align,
  className,
}: QuietMenuProps) {
  return (
    <Menu label={help} items={items} {...(align === undefined ? {} : { align })}>
      {(trigger) => (
        <button
          {...trigger}
          className={className === undefined ? "dk-quiet" : `dk-quiet ${className}`}
          title={help}
          aria-label={`${help}: ${title}`}
          style={tint === undefined ? undefined : { color: tint }}
        >
          <span className="dk-quiet-t">{title}</span>
          {chevron && (
            <svg className="dk-quiet-c" viewBox="0 0 12 12" aria-hidden="true">
              <path d="M3 4.5L6 7.5l3-3" />
            </svg>
          )}
        </button>
      )}
    </Menu>
  );
}
