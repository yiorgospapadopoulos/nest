import { act } from "@testing-library/react";
import { expect } from "vitest";
import type { SocketLike } from "../api/events.ts";
import type { NestEvent } from "../api/types.ts";

/** A socket the test drives: open it, push events, close it with a code. */
export class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((message: { data: unknown }) => void) | null = null;
  onclose: ((close: { code: number }) => void) | null = null;
  closed = false;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
  }

  open(): void {
    this.onopen?.();
  }

  emit(event: Partial<NestEvent> & { type: string }): void {
    const full: NestEvent = {
      id: null,
      ts: "2026-10-06T10:00:00Z",
      session_id: null,
      payload: {},
      ...event,
    };
    this.onmessage?.({ data: JSON.stringify(full) });
  }

  raw(data: unknown): void {
    this.onmessage?.({ data });
  }

  drop(code: number): void {
    this.onclose?.({ code });
  }

  close(): void {
    this.closed = true;
  }
}

export function socketFactory() {
  const sockets: FakeSocket[] = [];
  // Replaced by the first socket the app opens.
  let latest = new FakeSocket("");
  const connect = (url: string) => {
    latest = new FakeSocket(url);
    sockets.push(latest);
    return latest;
  };
  const last = () => latest;
  /**
   * A daemon restart or a phone waking up: the socket drops and the app connects again.
   * Going online skips the back-off, which `events.test.ts` covers with fake timers.
   */
  const reconnect = () => {
    const count = sockets.length;
    act(() => {
      latest.drop(1006);
      window.dispatchEvent(new Event("online"));
    });
    expect(sockets).toHaveLength(count + 1);
    act(() => {
      latest.open();
    });
  };
  return { sockets, connect, last, reconnect };
}
