// Regression (B117 VM check): the pill's list opened the moment the pointer crossed the
// strip on its way to the window below, then held open under the pointer and covered the
// + popover; and a hover that only passed by left it open. The list opens once the pointer
// rests on the strip, stays open over the strip and the open list, and closes 250 ms after
// the pointer leaves them, as the Mac's IslandView.pointer.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HOVER_OPEN_MS, LIST_CLOSE_MS, pillHover, POLL_MS, type Zone } from "./pillHover.ts";

let opened: boolean[];
let hover: ReturnType<typeof pillHover>;
// What the window system says: where the pointer really is, as the page last heard it
// unless a test says otherwise.
let really: Zone | null;
let heard: Zone;

beforeEach(() => {
  vi.useFakeTimers();
  opened = [];
  really = null;
  heard = "out";
  hover = pillHover(
    (open) => {
      opened.push(open);
    },
    () => Promise.resolve(really ?? heard),
    {
      later: (run, ms) => Number(setTimeout(run, ms)),
      cancel: (id) => {
        clearTimeout(id);
      },
    },
  );
});

afterEach(() => {
  hover.dispose();
  vi.useRealTimers();
});

const at = (zone: Zone, x = 100, y = 17) => {
  heard = zone;
  hover.move({ x, y }, zone);
};
const wait = (ms: number) => vi.advanceTimersByTimeAsync(ms);

describe("the pill's hover", () => {
  it("opens the list once the pointer rests on the strip", async () => {
    at("strip");
    await wait(HOVER_OPEN_MS - 1);
    expect(opened).toEqual([]);
    await wait(1);
    expect(opened).toEqual([true]);
  });

  it("does not open for a pointer passing over the strip", async () => {
    at("strip", 100, 2);
    await wait(40);
    at("strip", 100, 20);
    await wait(40);
    at("list", 100, 50);
    await wait(HOVER_OPEN_MS * 4);
    expect(opened).toEqual([]);
  });

  it("waits while the pointer keeps moving along the strip", async () => {
    for (let x = 0; x < 200; x += 20) {
      at("strip", x);
      await wait(HOVER_OPEN_MS / 2);
    }
    expect(opened).toEqual([]);
    // A hand at rest shakes by a pixel or two.
    at("strip", 181);
    await wait(HOVER_OPEN_MS);
    expect(opened).toEqual([true]);
  });

  it("stays open over the open list and closes after the pointer leaves", async () => {
    at("strip");
    await wait(HOVER_OPEN_MS);
    at("list", 100, 80);
    await wait(LIST_CLOSE_MS * 4);
    expect(opened).toEqual([true]);
    at("out", 100, 300);
    await wait(LIST_CLOSE_MS - 1);
    expect(opened).toEqual([true]);
    await wait(1);
    expect(opened).toEqual([true, false]);
  });

  it("keeps the list when the pointer comes back before it closes", async () => {
    at("strip");
    await wait(HOVER_OPEN_MS);
    hover.leave();
    await wait(LIST_CLOSE_MS - 50);
    at("list", 100, 80);
    await wait(LIST_CLOSE_MS * 2);
    expect(opened).toEqual([true]);
  });

  it("closes when the pointer leaves the window", async () => {
    at("strip");
    await wait(HOVER_OPEN_MS);
    hover.leave();
    await wait(LIST_CLOSE_MS);
    expect(opened).toEqual([true, false]);
  });

  it("counts the list's place as hot only while the list is open", async () => {
    // Where the list will be is not the strip: resting there opens nothing.
    at("list", 100, 80);
    await wait(HOVER_OPEN_MS * 4);
    expect(opened).toEqual([]);
  });

  it("opens at once for the +N, until the pointer leaves", async () => {
    at("strip");
    hover.pin();
    expect(opened).toEqual([true]);
    await wait(HOVER_OPEN_MS * 4);
    expect(opened).toEqual([true]);
    hover.leave();
    await wait(LIST_CLOSE_MS);
    expect(opened).toEqual([true, false]);
  });

  it("stays closed after a click until the pointer moves on or leaves", async () => {
    at("strip");
    await wait(HOVER_OPEN_MS);
    hover.dismiss();
    expect(opened).toEqual([true, false]);
    at("strip", 103);
    await wait(HOVER_OPEN_MS * 4);
    expect(opened).toEqual([true, false]);
    // Moving on along the strip, even with no leave heard, lets it open again.
    at("strip", 130);
    await wait(HOVER_OPEN_MS);
    expect(opened).toEqual([true, false, true]);
  });

  // Regression (B117 VM check): after a click on a pixie the pointer left, and the list
  // opened again and stayed open with the pointer far away. WebKit repeats the last move
  // after the page's layout changes, at the last place the pointer was inside.
  it("opens only where the window system finds the pointer on the strip", async () => {
    really = "out";
    at("strip", 120);
    await wait(HOVER_OPEN_MS * 4);
    expect(opened).toEqual([]);
  });

  it("closes a list the pointer left without the page hearing it", async () => {
    at("strip");
    await wait(HOVER_OPEN_MS);
    expect(opened).toEqual([true]);
    really = "out";
    await wait(POLL_MS + LIST_CLOSE_MS);
    expect(opened).toEqual([true, false]);
  });

  it("keeps the list open while the pointer stays on it", async () => {
    at("strip");
    await wait(HOVER_OPEN_MS);
    at("list", 100, 80);
    await wait(POLL_MS * 10);
    expect(opened).toEqual([true]);
  });
});
