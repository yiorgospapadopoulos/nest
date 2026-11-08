import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { focusComposer, onComposerFocus } from "./composerFocus.ts";

describe("focusComposer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("focuses a composer that is already there", () => {
    const focus = vi.fn();
    const stop = onComposerFocus("session:a", focus);
    focusComposer("session:a");
    vi.runAllTimers();
    expect(focus).toHaveBeenCalledOnce();
    stop();
  });

  // B147: a chat the palette opened in a new pane lost the keyboard to the page.
  it("reaches a composer that mounts after the request, once", () => {
    focusComposer("session:b");
    vi.runAllTimers();
    const focus = vi.fn();
    const stop = onComposerFocus("session:b", focus);
    vi.runAllTimers();
    expect(focus).toHaveBeenCalledOnce();
    stop();
    const later = vi.fn();
    const stopLater = onComposerFocus("session:b", later);
    vi.runAllTimers();
    expect(later).not.toHaveBeenCalled();
    stopLater();
  });
});
