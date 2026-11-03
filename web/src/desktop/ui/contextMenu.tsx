import { useRef, useState, type MouseEvent } from "react";
import { OpenMenu, type MenuPress } from "./Menu.tsx";
import type { MenuEntry } from "./menuItems.ts";

/**
 * A menu at the pointer on a right click (or the keyboard's menu key, at the element), as
 * the Mac's contextMenu. Spread `onContextMenu` on the element and render `menu`.
 */
export function useContextMenu(label: string, items: () => MenuEntry[]) {
  const pressing = useRef<MenuPress | null>(null);
  const [open, setOpen] = useState<{ entries: MenuEntry[]; at: { x: number; y: number } } | null>(
    null,
  );
  const onContextMenu = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const entries = items();
    if (entries.length === 0) return;
    let at = { x: event.clientX, y: event.clientY };
    if (at.x === 0 && at.y === 0) {
      const r = event.currentTarget.getBoundingClientRect();
      at = { x: r.left + 8, y: r.bottom };
    }
    // On Linux the menu opens on the press; its release over an item, after moving to it,
    // chooses it.
    pressing.current = event.button === 2 ? { x: at.x, y: at.y, moved: false } : null;
    setOpen({ entries, at });
  };
  const menu =
    open === null ? null : (
      <OpenMenu
        key={`${String(open.at.x)},${String(open.at.y)}`}
        entries={open.entries}
        label={label}
        where={{ point: open.at }}
        onClose={() => {
          setOpen(null);
        }}
        highlightFirst={false}
        pressing={pressing}
      />
    );
  return { onContextMenu, menu, open: open !== null };
}
