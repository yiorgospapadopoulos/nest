import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent, { PointerEventsCheckLevel, type UserEvent } from "@testing-library/user-event";
import { expect, vi } from "vitest";
import type { NestEvent } from "../api/types.ts";
import { App } from "../App.tsx";
import { fakeApi, type FakeApi } from "./fakeApi.ts";
import { socketFactory } from "./fakeSocket.ts";

/** A Storage that lives in memory, so tests never share saved appearance. */
export function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => {
      items.set(key, value);
    },
    removeItem: (key: string) => {
      items.delete(key);
    },
  } as unknown as Storage;
}

interface Options {
  api?: FakeApi;
  storage?: Storage;
  // Wait until the tabs show, as after a successful load.
  ready?: boolean;
}

/** The whole app over a fake API and socket. */
export async function renderApp({
  api = fakeApi(),
  storage = memoryStorage(),
  ready = true,
}: Options = {}) {
  const sockets = socketFactory();
  // No pause between keystrokes and no pointer-events walk up the tree on every action:
  // both cost time on each step and neither is what these tests are about.
  const user = userEvent.setup({ delay: null, pointerEventsCheck: PointerEventsCheckLevel.Never });
  const view = render(
    <App
      api={api}
      connect={sockets.connect}
      storage={() => storage}
      location={{ protocol: "https:", host: "mac.ts.net" }}
    />,
  );
  if (ready) {
    await screen.findByRole("tablist", { name: "Sections" });
    // The event socket opens in an effect right after the first load.
    await waitFor(() => {
      expect(sockets.sockets).not.toHaveLength(0);
    });
  }
  const push = (event: Partial<NestEvent> & { type: string }) => {
    act(() => {
      sockets.last().emit(event);
    });
  };
  return { ...view, api, sockets, user, storage, push };
}

/** Types with the clock faked, then lets `ms` pass: a debounce is waited out without real time. */
export async function typeAndWait(user: UserEvent, element: Element, text: string, ms: number) {
  // The clock still runs along: Testing Library's wrapper waits on a real zero timeout.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    await user.type(element, text);
    await act(() => vi.advanceTimersByTimeAsync(ms));
  } finally {
    vi.useRealTimers();
  }
}

/** Fills a free-text field in one paste, where the keystrokes are not what a test is about. */
export async function fill(user: UserEvent, field: HTMLElement, text: string) {
  await user.click(field);
  await user.paste(text);
}
