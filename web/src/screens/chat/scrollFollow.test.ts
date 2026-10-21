import { describe, expect, it } from "vitest";
import { isAtBottom, ScrollFollow, type ScrollMetrics } from "./scrollFollow.ts";

// The Mac's rule (D099, NestKit ScrollFollow), as its tests check it: a viewport of 500
// over `content`, scrolled to `offset`.
const metrics = (offset: number, content: number, viewport = 500): ScrollMetrics => ({
  offset,
  viewport,
  content,
});

/** A transcript at the bottom of 1000 points of content, following. */
function atBottom(): ScrollFollow {
  const follow = new ScrollFollow();
  follow.update(metrics(500, 1000));
  return follow;
}

describe("scroll follow", () => {
  it("counts the last 40 points as the bottom", () => {
    expect(isAtBottom(metrics(500, 1000))).toBe(true);
    expect(isAtBottom(metrics(461, 1000))).toBe(true);
    expect(isAtBottom(metrics(459, 1000))).toBe(false);
    expect(isAtBottom(metrics(0, 300))).toBe(true);
  });

  it("follows from the start and keeps following as content grows", () => {
    const follow = new ScrollFollow();
    expect(follow.following).toBe(true);
    expect(follow.update(metrics(500, 1000))).toBe(false);
    // Growth moves the bottom away: the view scrolls down rather than stop following.
    expect(follow.update(metrics(500, 1300))).toBe(true);
    expect(follow.following).toBe(true);
    expect(follow.contentArrived()).toBe(true);
    expect(follow.showsJump).toBe(false);
  });

  it("stops following on a move up, and then nothing moves the view", () => {
    const follow = atBottom();
    expect(follow.update(metrics(200, 1000))).toBe(false);
    expect(follow.following).toBe(false);
    // Streaming text, a sent message and the keyboard opening all leave it alone.
    expect(follow.update(metrics(200, 1400))).toBe(false);
    expect(follow.contentArrived()).toBe(false);
    expect(follow.update(metrics(200, 1400, 300))).toBe(false);
    expect(follow.following).toBe(false);
    expect(follow.showsJump).toBe(true);
  });

  it("stops following on a small move up inside the bottom zone", () => {
    const follow = atBottom();
    expect(follow.update(metrics(495, 1000))).toBe(false);
    expect(follow.following).toBe(false);
    expect(follow.contentArrived()).toBe(false);
    expect(follow.update(metrics(490, 1000))).toBe(false);
    expect(follow.update(metrics(490, 1200))).toBe(false);
    expect(follow.following).toBe(false);
  });

  it("stops following on a move up while text streams in", () => {
    const follow = atBottom();
    // The scroll and the growth arrive in one change.
    expect(follow.update(metrics(480, 1100))).toBe(false);
    expect(follow.following).toBe(false);
    // Back down into the bottom zone while it still streams: following again.
    expect(follow.update(metrics(620, 1150))).toBe(false);
    expect(follow.following).toBe(true);
  });

  it("keeps following through moves the user did not make", () => {
    const follow = atBottom();
    // Content that shrinks pulls the offset up to the new end.
    expect(follow.update(metrics(400, 900))).toBe(false);
    expect(follow.following).toBe(true);
    // A bounce past the end settles back on it.
    follow.update(metrics(420, 900));
    expect(follow.update(metrics(400, 900))).toBe(false);
    expect(follow.following).toBe(true);
    // A taller view pulls the offset up to the end too.
    expect(follow.update(metrics(300, 900, 600))).toBe(false);
    expect(follow.following).toBe(true);
  });

  it("resumes only on a move down into the bottom zone", () => {
    const follow = atBottom();
    follow.update(metrics(100, 1000));
    follow.contentArrived();
    // Down, but not to the bottom: still reading.
    expect(follow.update(metrics(300, 1000))).toBe(false);
    expect(follow.following).toBe(false);
    expect(follow.update(metrics(480, 1000))).toBe(false);
    expect(follow.following).toBe(true);
    expect(follow.showsJump).toBe(false);
    expect(follow.update(metrics(480, 1100))).toBe(true);
  });

  it("offers Jump to latest while it does not follow, and jumping follows again", () => {
    const follow = atBottom();
    follow.update(metrics(100, 1000));
    expect(follow.showsJump).toBe(true);
    follow.jumpToLatest();
    expect(follow.following).toBe(true);
    expect(follow.showsJump).toBe(false);
    // While the jump scrolls, growth keeps the view heading for the bottom.
    expect(follow.update(metrics(300, 1200))).toBe(true);
    // The jump's own steps do not count as the user's, until it reached the bottom.
    follow.update(metrics(200, 1200));
    expect(follow.following).toBe(true);
    follow.update(metrics(700, 1200));
    follow.update(metrics(400, 1200));
    expect(follow.following).toBe(false);
  });

  it("ends a jump made at the bottom at once", () => {
    const follow = atBottom();
    follow.jumpToLatest();
    // Nothing scrolls after it, so the next move up is the user's.
    follow.update(metrics(200, 1000));
    expect(follow.following).toBe(false);
  });

  it("holds an earlier item, such as a search hit, until the user returns", () => {
    const follow = new ScrollFollow();
    follow.jumpToLatest();
    follow.hold();
    expect(follow.following).toBe(false);
    // A scroll to the hit, then growth: nothing pulls the view down.
    expect(follow.update(metrics(200, 1000))).toBe(false);
    expect(follow.update(metrics(200, 1400))).toBe(false);
    expect(follow.contentArrived()).toBe(false);
    expect(follow.update(metrics(900, 1400))).toBe(false);
    expect(follow.following).toBe(true);
  });
});
