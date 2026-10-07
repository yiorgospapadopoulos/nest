import type { SocketLike } from "../api/events.ts";
import type { HarnessEvent } from "../api/types.ts";

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

  emit(event: Partial<HarnessEvent> & { type: string }): void {
    const full: HarnessEvent = {
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
  return { sockets, connect, last };
}
