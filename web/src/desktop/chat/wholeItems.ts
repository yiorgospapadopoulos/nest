// The composer's selectors in a narrow pane: a label is shown whole, in PaneFit's short
// form, or the selector leaves the row; it is never cut mid-word ("Hai…", "A…").
import { useLayoutEffect, type RefObject } from "react";

export interface Droppable {
  // Lower goes first.
  drop: number;
  width: number;
}

/**
 * Which items leave a row that is `overflow` pixels too wide: the lowest `drop` first,
 * each giving back its width and one `gap`, until the rest fits.
 */
export function itemsToDrop(overflow: number, items: Droppable[], gap: number): Set<number> {
  const dropped = new Set<number>();
  let left = overflow;
  for (const item of [...items].sort((a, b) => a.drop - b.drop)) {
    if (left <= 0) break;
    dropped.add(item.drop);
    left -= item.width + gap;
  }
  return dropped;
}

/**
 * Keeps the row's `[data-drop]` children whole: after every render and resize, those the
 * row has no room for are marked `data-dropped` (hidden by chat.css), lowest first.
 */
export function useWholeItems(row: RefObject<HTMLElement | null>): void {
  useLayoutEffect(() => {
    const element = row.current;
    if (element === null) return;
    const fit = () => {
      const items = [...element.querySelectorAll<HTMLElement>(":scope > [data-drop]")];
      for (const item of items) item.removeAttribute("data-dropped");
      const overflow = element.scrollWidth - element.clientWidth;
      if (overflow <= 0) return;
      const gap = Number.parseFloat(getComputedStyle(element).columnGap) || 0;
      const dropped = itemsToDrop(
        overflow,
        items.map((item) => ({ drop: Number(item.dataset.drop), width: item.offsetWidth })),
        gap,
      );
      for (const item of items) {
        if (dropped.has(Number(item.dataset.drop))) item.setAttribute("data-dropped", "");
      }
    };
    fit();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(fit);
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  });
}
