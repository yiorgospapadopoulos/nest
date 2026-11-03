import type { TranscriptItem } from "../../transcript/build.ts";

/**
 * From how many items a transcript draws only the ones near the screen (B117). Below it
 * every item is in the page as before, so in-page find, selection and the browser's own
 * scrolling see the whole chat. Measured on WebKitGTK with a reply streaming: 150 items
 * in full stream as smoothly as a windowed list, 300 drop to about half the frame rate,
 * since every streamed word draws each item again.
 */
export const VIRTUAL_FROM = 200;

/** The event an item came from: its key's leading number. */
export function eventOf(item: TranscriptItem): number {
  return Number.parseInt(item.key, 10);
}

/**
 * The index of the item shown for an event: the last one at or before it, since a tool
 * result shows with its call. Null when every item comes after it.
 */
export function itemIndexAt(items: readonly TranscriptItem[], eventId: number): number | null {
  let found: number | null = null;
  for (const [index, item] of items.entries()) {
    const event = eventOf(item);
    if (Number.isNaN(event)) continue;
    if (event > eventId) break;
    found = index;
  }
  return found;
}

/**
 * The element shown for an event among those in `box`: the last one at or before it,
 * since a tool result shows with its call.
 */
export function nearestItem(box: HTMLElement, eventId: number): HTMLElement | null {
  let found: HTMLElement | null = null;
  for (const node of box.querySelectorAll<HTMLElement>("[data-ev]")) {
    if (Number(node.dataset.ev) > eventId) break;
    found = node;
  }
  return found;
}
