import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HEARTBEAT_MS, reportVisibility, type VisibilityEnv } from "./visibility.ts";

class FakeDocument extends EventTarget {
  visibilityState: DocumentVisibilityState = "visible";

  show(state: DocumentVisibilityState) {
    this.visibilityState = state;
    this.dispatchEvent(new Event("visibilitychange"));
  }
}

function setup(initial: DocumentVisibilityState = "visible") {
  const doc = new FakeDocument();
  doc.visibilityState = initial;
  const report = vi.fn<VisibilityEnv["report"]>().mockResolvedValue(null);
  const stop = reportVisibility({ document: doc, report });
  return { doc, report, stop };
}

describe("visibility reports", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("reports on start and every minute while visible", () => {
    const { report, stop } = setup();

    expect(report.mock.calls).toEqual([[true]]);
    vi.advanceTimersByTime(HEARTBEAT_MS);
    vi.advanceTimersByTime(HEARTBEAT_MS);
    expect(report.mock.calls).toEqual([[true], [true], [true]]);
    stop();
  });

  it("reports hiding and showing, with no heartbeat while hidden", () => {
    const { doc, report, stop } = setup("hidden");
    expect(report.mock.calls).toEqual([[false]]);

    vi.advanceTimersByTime(3 * HEARTBEAT_MS);
    doc.show("visible");
    doc.show("hidden");
    vi.advanceTimersByTime(3 * HEARTBEAT_MS);

    expect(report.mock.calls).toEqual([[false], [true], [false]]);
    stop();
  });

  it("stops listening and reports hidden when stopped", () => {
    const { doc, report, stop } = setup();

    stop();
    doc.show("visible");
    vi.advanceTimersByTime(3 * HEARTBEAT_MS);

    expect(report.mock.calls).toEqual([[true], [false]]);
  });

  it("ignores failed reports", async () => {
    const doc = new FakeDocument();
    const report = vi.fn<VisibilityEnv["report"]>().mockRejectedValue(new Error("offline"));

    const stop = reportVisibility({ document: doc, report });
    await vi.runOnlyPendingTimersAsync();
    stop();

    expect(report).toHaveBeenCalled();
  });
});
