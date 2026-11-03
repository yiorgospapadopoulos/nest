import { useVirtualizer } from "@tanstack/react-virtual";
import { memo, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import type { ScrollFollow } from "../../screens/chat/scrollFollow.ts";
import { itemIndexAt, nearestItem } from "../../screens/chat/virtualRows.ts";
import type { TranscriptItem } from "../../transcript/build.ts";

// A guess for an item not drawn yet; each is measured once drawn.
const ESTIMATE = 80;
// Items drawn beyond each edge of the screen, so a short scroll or a find nearby has them.
const OVERSCAN = 4;

interface Props {
  items: TranscriptItem[];
  follow: RefObject<ScrollFollow>;
  // An event to bring on screen, and the last one brought, shared with the full list.
  focus: number | null;
  focused: RefObject<number | null>;
  onHit: (target: HTMLElement) => void;
  renderItem: (item: TranscriptItem) => ReactNode;
}

/**
 * A long transcript's items, only those near the screen in the page (B117, the phone's
 * VirtualItems). Following stays with ScrollFollow (D099): the list never scrolls to the
 * end by itself, and the reader's place holds when items above change height or older
 * ones come in. An opened row keeps its open state outside the row (expanded.ts).
 */
export function VirtualList({ items, follow, focus, focused, onHit, renderItem }: Props) {
  const list = useRef<HTMLDivElement>(null);
  // Found from the list: on mount the list's effects run before the pane's ref is set.
  const scroller = () => list.current?.closest<HTMLElement>(".dc-tx") ?? null;
  const [margin, setMargin] = useState(0);
  // eslint-disable-next-line react-hooks/incompatible-library -- not memoised by the compiler
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: scroller,
    estimateSize: () => ESTIMATE,
    getItemKey: (index) => items[index]?.key ?? index,
    overscan: OVERSCAN,
    scrollMargin: margin,
    // Keeps the item at the top in place when items come in before it.
    anchorTo: "end",
    // Never "at the end" for the list itself: whether to follow is ScrollFollow's call.
    scrollEndThreshold: -1,
    // A chat opens at its end, so the first drawing is already the last items.
    initialOffset: () => (follow.current.following ? items.length * ESTIMATE : 0),
  });
  const total = virtualizer.getTotalSize();
  const rows = virtualizer.getVirtualItems();

  useLayoutEffect(() => {
    const el = scroller();
    if (el !== null) setMargin(Number.parseFloat(getComputedStyle(el).paddingTop) || 0);
  }, []);

  // Items measured taller or shorter change the length; a followed chat stays at its end.
  useLayoutEffect(() => {
    const el = scroller();
    if (el !== null && follow.current.contentArrived()) el.scrollTop = el.scrollHeight;
  }, [total, follow]);

  // A search hit: scroll to its item until it is drawn, then show it as the full list does.
  const asked = useRef<number | null>(null);
  useLayoutEffect(() => {
    const el = scroller();
    if (focus === null || focused.current === focus || el === null) return;
    const index = itemIndexAt(items, focus);
    if (index === null) return;
    follow.current.hold();
    const row = el.querySelector<HTMLElement>(`[data-index="${String(index)}"]`);
    if (row === null) {
      if (asked.current !== focus) {
        asked.current = focus;
        virtualizer.scrollToIndex(index, { align: "center" });
      }
      return;
    }
    focused.current = focus;
    onHit(nearestItem(row, focus) ?? row);
  });

  return (
    <div className="dc-tx-v" ref={list} style={{ height: total }}>
      {rows.map((row) => {
        const item = items[row.index];
        if (item === undefined) return null;
        return (
          <div
            key={row.key.toString()}
            className="dc-tx-row"
            data-index={row.index}
            ref={virtualizer.measureElement}
            style={{ transform: `translateY(${String(row.start - margin)}px)` }}
          >
            <Row item={item} render={renderItem} />
          </div>
        );
      })}
    </div>
  );
}

// Scrolling draws the list again at each new range; an item already drawn is left alone.
const Row = memo(function Row({
  item,
  render,
}: {
  item: TranscriptItem;
  render: (item: TranscriptItem) => ReactNode;
}) {
  return render(item);
});
