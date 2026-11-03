// Regressions (B117 audit, P1): a new chat's draft pane could not be closed; Ctrl+W closed
// the pane behind an open Settings window or palette; Ctrl+N did nothing in the Pixies tab.
// As the Mac's closeFocused, Ctrl+W closes the topmost overlay first, then the focused pane.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { memoryStorage } from "../../test/render.tsx";
import { browserBridge } from "../bridge.ts";
import { DesktopApp } from "../DesktopApp.tsx";

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {
      return undefined;
    }
    unobserve() {
      return undefined;
    }
    disconnect() {
      return undefined;
    }
  };
  Element.prototype.scrollIntoView = () => undefined;
  // The workspace lays panes out by its measured size, which jsdom reports as zero.
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 1200 });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 800 });
});

async function renderDesktop() {
  const storage = memoryStorage();
  render(
    <DesktopApp
      bridge={browserBridge({ search: "" }, null)}
      api={fakeApi()}
      connect={socketFactory().connect}
      location={{ protocol: "http:", host: "127.0.0.1:8765" }}
      storage={() => storage}
    />,
  );
  await screen.findByRole("button", { name: "Settings" });
}

const ctrl = (key: string) => {
  fireEvent.keyDown(document.body, { key, code: `Key${key.toUpperCase()}`, ctrlKey: true });
};
const draft = () => screen.queryByRole("region", { name: "New chat" });

describe("a new chat's draft pane", () => {
  it("opens with its own header and closes with its X", async () => {
    await renderDesktop();
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    const pane = await screen.findByRole("region", { name: "New chat" });
    expect(within(pane).getByRole("heading", { name: "New chat" })).toBeInTheDocument();
    expect(within(pane).getByRole("textbox", { name: "Message" })).toBeInTheDocument();
    fireEvent.click(within(pane).getByRole("button", { name: "Close pane" }));
    expect(draft()).not.toBeInTheDocument();
  });
});

describe("Ctrl+W", () => {
  it("closes Settings, then the palette, then the focused pane, one at a time", async () => {
    await renderDesktop();
    ctrl("n");
    await screen.findByRole("region", { name: "New chat" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("region", { name: "Settings" })).toBeInTheDocument();
    ctrl("w");
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Settings" })).not.toBeInTheDocument();
    });
    expect(draft()).toBeInTheDocument();
    ctrl("k");
    expect(screen.getByRole("dialog", { name: "Search chats and commands" })).toBeInTheDocument();
    ctrl("w");
    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "Search chats and commands" }),
      ).not.toBeInTheDocument();
    });
    expect(draft()).toBeInTheDocument();
    ctrl("w");
    expect(draft()).not.toBeInTheDocument();
  });

  it("closes an open menu before the pane under it", async () => {
    await renderDesktop();
    ctrl("n");
    const pane = await screen.findByRole("region", { name: "New chat" });
    const place = within(pane).getByRole("button", { name: /^Where the chat works/ });
    fireEvent.pointerDown(place, { button: 0 });
    expect(screen.getByRole("menu")).toBeInTheDocument();
    act(() => {
      ctrl("w");
    });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(draft()).toBeInTheDocument();
  });
});

describe("Ctrl+N in the Pixies tab", () => {
  it("opens a draft in the last project tab, as the Mac", async () => {
    await renderDesktop();
    fireEvent.click(screen.getByRole("tab", { name: /^Pixies/ }));
    await waitFor(() => {
      expect(screen.getByRole("main", { name: "Pixies" })).toBeInTheDocument();
    });
    ctrl("n");
    await screen.findByRole("main", { name: "todo-ui" });
    expect(await screen.findByRole("region", { name: "New chat" })).toBeInTheDocument();
  });
});
