// Regression (production check, 2026-11-03): with no daemon at launch the window was a dead
// end, and a lost daemon showed only "Reconnecting...". As the Mac's ConnectionBanner and
// ServiceStarter (NestKitTests RemoteModelTests, ServiceStarterTests), the app keeps
// trying with the Mac's backoff, says when it tries again, and offers to start the service.
import { describe, expect, it } from "vitest";
import {
  backoffDelay,
  bannerActions,
  bannerText,
  installCommand,
  RetryLoop,
  startService,
  type Connection,
} from "./connection.ts";

function fakeTimers() {
  const waiting = new Map<number, { callback: () => void; ms: number }>();
  let next = 1;
  return {
    timers: {
      set: (callback: () => void, ms: number) => {
        waiting.set(next, { callback, ms });
        return next++;
      },
      clear: (id: number) => {
        waiting.delete(id);
      },
    },
    waiting,
    fire() {
      const [id, timer] = [...waiting.entries()][0] ?? [];
      if (id === undefined || timer === undefined) throw new Error("nothing waits");
      waiting.delete(id);
      timer.callback();
      return timer.ms;
    },
  };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("the connection banner", () => {
  it("keeps the Mac's words", () => {
    expect(bannerText({ kind: "connected" })).toBeNull();
    expect(bannerText({ kind: "connecting" })).toBeNull();
    expect(bannerText({ kind: "reconnecting", attempt: 2, delay: 7.2 })).toBe(
      "Can't reach the Nest daemon. Trying again in 8s",
    );
    expect(bannerText({ kind: "reconnecting", attempt: 1, delay: 0.5 })).toBe(
      "Reconnecting to the Nest daemon",
    );
  });

  it("offers Retry and Start Nest service while unreachable, nothing while it starts", () => {
    const lost: Connection = { kind: "reconnecting", attempt: 3, delay: 2 };
    expect(bannerActions(lost, { kind: "idle" })).toEqual(["retry", "startService"]);
    expect(bannerActions(lost, { kind: "starting" })).toEqual([]);
    expect(bannerActions({ kind: "connected" }, { kind: "idle" })).toEqual(["retry"]);
  });

  it("backs off as the Mac: half a second, doubled, at most 30", () => {
    expect([1, 2, 3, 4, 7, 8, 20].map(backoffDelay)).toEqual([0.5, 1, 2, 4, 30, 30, 30]);
  });
});

describe("starting the service", () => {
  it("reports a start, a missing unit with the install command, or why it failed", async () => {
    expect(await startService(() => Promise.resolve("started"))).toEqual({ kind: "started" });
    expect(await startService(() => Promise.resolve("not_installed"))).toEqual({
      kind: "notInstalled",
      command: installCommand(null),
    });
    expect(
      await startService(() => Promise.reject(new Error("Job for nest.service failed"))),
    ).toEqual({ kind: "failed", reason: "Job for nest.service failed" });
  });

  // Re-check (2026-11-03): a bare "nestd service install" did not run as pasted, since
  // nestd is not on the PATH. As the Mac's DaemonService.installCommand.
  it("gives an install command that runs as pasted, from the checkout", () => {
    expect(installCommand("/a/it's")).toBe(
      "cd '/a/it'\\''s/daemon' && uv run nestd service install",
    );
    expect(installCommand(null)).toBe(
      "cd <your Nest checkout>/daemon && uv run nestd service install",
    );
  });
});

describe("the retry loop", () => {
  it("keeps trying with longer waits until the daemon answers", async () => {
    const clock = fakeTimers();
    const seen: Connection[] = [];
    let answers = false;
    const loop = new RetryLoop(
      () => Promise.resolve(answers),
      (c) => seen.push(c),
      clock.timers,
    );
    loop.start();
    await settle();
    expect(clock.fire()).toBe(500);
    await settle();
    expect(clock.fire()).toBe(1000);
    await settle();
    answers = true;
    expect(clock.fire()).toBe(2000);
    await settle();
    expect(seen).toEqual([
      { kind: "reconnecting", attempt: 1, delay: 0.5 },
      { kind: "reconnecting", attempt: 2, delay: 1 },
      { kind: "reconnecting", attempt: 3, delay: 2 },
      { kind: "connected" },
    ]);
    expect(clock.waiting.size).toBe(0);
  });

  it("tries again at once on Retry, from the first delay, and stops when told", async () => {
    const clock = fakeTimers();
    const seen: Connection[] = [];
    let tries = 0;
    const loop = new RetryLoop(
      () => {
        tries += 1;
        return Promise.reject(new Error("refused"));
      },
      (c) => seen.push(c),
      clock.timers,
    );
    loop.start();
    await settle();
    clock.fire();
    await settle();
    loop.retry();
    await settle();
    expect(tries).toBe(3);
    expect(seen.at(-1)).toEqual({ kind: "reconnecting", attempt: 1, delay: 0.5 });
    expect(clock.waiting.size).toBe(1);
    loop.stop();
    expect(clock.waiting.size).toBe(0);
  });
});
