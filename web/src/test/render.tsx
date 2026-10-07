import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect } from "vitest";
import type { HarnessEvent } from "../api/types.ts";
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
  const user = userEvent.setup();
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
  const push = (event: Partial<HarnessEvent> & { type: string }) => {
    act(() => {
      sockets.last().emit(event);
    });
  };
  return { ...view, api, sockets, user, storage, push };
}
