import { afterEach, describe, expect, it, vi } from "vitest";
import { socketFactory } from "../test/fakeSocket.ts";
import { EventStream, eventsUrl, MAX_DELAY_MS, type Timers } from "./events.ts";

function fakeTimers() {
  const pending = new Map<number, { callback: () => void; ms: number }>();
  let next = 1;
  const timers: Timers = {
    set: (callback, ms) => {
      pending.set(next, { callback, ms });
      return next++;
    },
    clear: (id) => pending.delete(id),
  };
  const fire = () => {
    const [id, entry] = [...pending.entries()][0] ?? [];
    if (id === undefined || entry === undefined) throw new Error("no timer pending");
    pending.delete(id);
    entry.callback();
    return entry.ms;
  };
  return { timers, pending, fire };
}

function setup() {
  const factory = socketFactory();
  const handlers = { onEvent: vi.fn(), onOpen: vi.fn(), onClosed: vi.fn() };
  const clock = fakeTimers();
  const stream = new EventStream(
    factory.connect,
    (after) => `ws://x/api/events${after === null ? "" : `?after=${String(after)}`}`,
    handlers,
    clock.timers,
  );
  return { factory, handlers, clock, stream };
}

describe("eventsUrl", () => {
  it("uses wss on https and adds the cursor", () => {
    expect(eventsUrl({ protocol: "https:", host: "mac.ts.net" }, 12)).toBe(
      "wss://mac.ts.net/api/events?after=12",
    );
    expect(eventsUrl({ protocol: "http:", host: "127.0.0.1:8765" }, null)).toBe(
      "ws://127.0.0.1:8765/api/events",
    );
  });
});

describe("EventStream", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("forwards events and moves the cursor only for stored ones", () => {
    const { factory, handlers, stream } = setup();
    stream.start();
    const socket = factory.last();
    socket.open();

    socket.emit({ id: 5, type: "session.message" });
    socket.emit({ id: null, type: "session.delta" });
    socket.emit({ id: 3, type: "old" });
    socket.raw("not json");
    socket.raw(new Blob());

    expect(handlers.onOpen).toHaveBeenCalledWith(false);
    expect(handlers.onEvent).toHaveBeenCalledTimes(3);
    expect(stream.cursor).toBe(5);
  });

  it("reconnects with the cursor and a capped exponential backoff", () => {
    const { factory, handlers, clock, stream } = setup();
    stream.start();
    factory.last().open();
    factory.last().emit({ id: 7, type: "x" });

    const delays: number[] = [];
    for (let i = 0; i < 7; i++) {
      factory.last().drop(1006);
      delays.push(clock.fire());
    }

    expect(delays).toEqual([1000, 2000, 4000, 8000, 16000, MAX_DELAY_MS, MAX_DELAY_MS]);
    expect(factory.last().url).toBe("ws://x/api/events?after=7");
    factory.last().open();
    expect(handlers.onOpen).toHaveBeenLastCalledWith(true);
    factory.last().drop(1013);
    expect(clock.fire()).toBe(1000);
  });

  it.each([
    [4401, "unauthorized"],
    [4403, "forbidden"],
  ])("stops for good on close code %i", (code, reason) => {
    const { factory, handlers, clock, stream } = setup();
    stream.start();

    factory.last().drop(code);

    expect(handlers.onClosed).toHaveBeenCalledWith(reason);
    expect(clock.pending.size).toBe(0);
  });

  it("stop closes the socket and cancels a pending reconnect", () => {
    const { factory, clock, stream } = setup();
    stream.start();
    const first = factory.last();
    first.drop(1006);
    expect(clock.pending.size).toBe(1);

    stream.stop();
    expect(clock.pending.size).toBe(0);

    stream.start();
    const second = factory.last();
    stream.stop();
    expect(second.closed).toBe(true);
    second.drop(1000);
    expect(clock.pending.size).toBe(0);
    stream.stop();
  });

  it("ignores a close after stop of the same socket", () => {
    const { factory, clock, stream } = setup();
    stream.start();
    const socket = factory.last();
    stream.stop();
    stream.start();
    socket.drop(1006);
    expect(clock.pending.size).toBe(0);
  });

  it("uses browser timers by default", () => {
    vi.useFakeTimers();
    const factory = socketFactory();
    const stream = new EventStream(factory.connect, () => "ws://x", {
      onEvent: vi.fn(),
      onOpen: vi.fn(),
      onClosed: vi.fn(),
    });
    stream.start();
    factory.last().drop(1006);
    vi.advanceTimersByTime(1000);
    expect(factory.sockets).toHaveLength(2);
    factory.last().drop(1006);
    stream.stop();
    vi.advanceTimersByTime(5000);
    expect(factory.sockets).toHaveLength(2);
  });
});
