// When the pill's list opens and closes (B117), as the Mac's IslandView.pointer: over the
// strip, or over the list while it is open, the pointer keeps it open, and 250 ms after it
// leaves them the list closes. The pill here sits over the top of Nest's own window rather
// than in the menu bar, so the list opens only once the pointer rests on the strip: one on
// its way to the window below passes without the list opening under it.
//
// The page's pointer events are not the whole truth: WebKit repeats the last move after a
// layout change, also when the pointer has left, and a leave can go missing. So, as the
// Mac's island follows the pointer on screen, the list opens only when the window system
// says the pointer is on the strip, and while it is open it is asked again now and then.

/** Where the pointer is: on the strip, on the rest of the pill, or elsewhere. */
export type Zone = "strip" | "list" | "out";

// The pointer rests on the strip this long before the list opens.
export const HOVER_OPEN_MS = 150;
// The list closes this long after the pointer leaves the strip and the open list.
export const LIST_CLOSE_MS = 250;
// While the list is open, where the pointer really is is asked this often.
export const POLL_MS = 400;
// A move shorter than this is a hand at rest.
const REST_PX = 3;
// After a click, the list opens again only once the pointer moved this far or left.
const DISMISS_PX = 8;

interface Clock {
  later(run: () => void, ms: number): number;
  cancel(id: number): void;
}

const browserClock: Clock = {
  later: (run, ms) => window.setTimeout(run, ms),
  cancel: (id) => {
    window.clearTimeout(id);
  },
};

/** Where the window system says the pointer is now; null when it cannot tell. */
export type Probe = () => Promise<Zone | null>;

export interface PillHover {
  // The pointer moved, here (screen px), in this zone of the pill.
  move(point: { x: number; y: number }, zone: Zone): void;
  // The pointer left the pill's window.
  leave(): void;
  // The +N: open now, until the pointer leaves.
  pin(): void;
  // A click opened Nest: closed, and it opens again only once the pointer moved on or left.
  dismiss(): void;
  dispose(): void;
}

interface Point {
  x: number;
  y: number;
}

const near = (a: Point, b: Point, px: number) =>
  Math.abs(a.x - b.x) <= px && Math.abs(a.y - b.y) <= px;

export function pillHover(
  show: (open: boolean) => void,
  probe: Probe = () => Promise.resolve(null),
  clock: Clock = browserClock,
): PillHover {
  let open = false;
  let opening: number | null = null;
  let closing: number | null = null;
  let polling: number | null = null;
  let anchor: Point | null = null;
  let last: Point | null = null;
  // Where a click closed the list, until the pointer moves on or leaves.
  let dismissed: Point | null = null;
  // Counts every change of mind, so a late probe answer for an old one is dropped.
  let turn = 0;
  let disposed = false;

  const stopOpening = () => {
    if (opening !== null) clock.cancel(opening);
    opening = null;
    anchor = null;
  };
  const stopClosing = () => {
    if (closing !== null) clock.cancel(closing);
    closing = null;
  };
  const stopPolling = () => {
    if (polling !== null) clock.cancel(polling);
    polling = null;
  };
  const poll = () => {
    polling = clock.later(() => {
      polling = null;
      const asked = turn;
      void probe().then((zone) => {
        if (disposed || !open) return;
        if (zone === "out" && asked === turn) away("out");
        poll();
      });
    }, POLL_MS);
  };
  const set = (next: boolean) => {
    if (next === open) return;
    open = next;
    stopPolling();
    if (next) poll();
    show(next);
  };
  const away = (zone: Zone) => {
    turn++;
    stopOpening();
    if (zone !== "strip") dismissed = null;
    if (open && closing === null) {
      closing = clock.later(() => {
        closing = null;
        set(false);
      }, LIST_CLOSE_MS);
    }
  };
  const startOpening = (point: Point) => {
    stopOpening();
    anchor = point;
    const asked = ++turn;
    opening = clock.later(() => {
      opening = null;
      anchor = null;
      void probe().then((zone) => {
        if (disposed || asked !== turn) return;
        // A repeated move after the pointer left: nothing is there.
        if (zone === "strip" || zone === null) set(true);
        else away(zone);
      });
    }, HOVER_OPEN_MS);
  };

  return {
    move(point, zone) {
      last = point;
      const hot = zone === "strip" || (open && zone === "list");
      if (!hot) {
        away(zone);
        return;
      }
      stopClosing();
      if (dismissed !== null && !near(point, dismissed, DISMISS_PX)) dismissed = null;
      if (open || dismissed !== null || zone !== "strip") return;
      if (opening !== null && anchor !== null && near(point, anchor, REST_PX)) return;
      startOpening(point);
    },
    leave() {
      away("out");
    },
    pin() {
      turn++;
      stopOpening();
      stopClosing();
      set(true);
    },
    dismiss() {
      turn++;
      stopOpening();
      stopClosing();
      dismissed = last ?? { x: 0, y: 0 };
      set(false);
    },
    dispose() {
      disposed = true;
      stopOpening();
      stopClosing();
      stopPolling();
    },
  };
}
