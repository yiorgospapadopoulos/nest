// Whether a pixie row shows its @handle, as the Mac's PixieRow decides with ViewThatFits:
// the handle gives way first, shown whole or not at all, and the name is cut only once it
// is gone. The Mac decides in SF; Inter under WebKitGTK draws the same text about 4% wider
// (measured: "New pixie" 57 against 54.8, "@new-pixie" 69 against 66.1), so the rule
// counts the text at SF's width. A row that fits on the Mac keeps its handle here, the
// name giving up those few pixels; one that does not fit there drops it here too.
import { useLayoutEffect, useState, type RefObject } from "react";

// How much wider Inter draws the same text than SF at the sidebar's size.
export const INTER_OVER_SF = 1.04;
// The gap between the name, Leader and the handle, as the Mac's HStack spacing.
export const LABEL_GAP = 6;

export interface LabelWidths {
  // Each part's whole width in Inter; `leader` is null for a row without the badge.
  name: number;
  leader: number | null;
  handle: number;
  // The width the label has in the row.
  available: number;
}

export function showsHandle({ name, leader, handle, available }: LabelWidths): boolean {
  const text = (name + handle) / INTER_OVER_SF;
  const badge = leader === null ? 0 : leader + LABEL_GAP;
  return text + badge + LABEL_GAP <= available;
}

/** Measures the label (name, optional badge, handle) and keeps the rule's answer. */
export function useShowsHandle(label: RefObject<HTMLElement | null>, text: string): boolean {
  const [shown, setShown] = useState(true);
  useLayoutEffect(() => {
    const element = label.current;
    if (element === null) return;
    const measure = () => {
      const name = element.querySelector<HTMLElement>(".px-name");
      const leader = element.querySelector<HTMLElement>(".px-leader");
      const handle = element.querySelector<HTMLElement>(".px-slug");
      if (name === null || handle === null) return;
      setShown(
        showsHandle({
          name: name.scrollWidth,
          leader: leader?.offsetWidth ?? null,
          handle: handle.offsetWidth,
          available: element.clientWidth,
        }),
      );
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    // The text's own boxes too: the label keeps its width when Inter arrives after the
    // first measure, or the text is zoomed, but the handle and the badge do not.
    for (const part of [element, ...element.querySelectorAll(".px-slug, .px-leader")]) {
      observer.observe(part);
    }
    return () => {
      observer.disconnect();
    };
  }, [label, text]);
  return shown;
}
