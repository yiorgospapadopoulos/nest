// A browser pane keeps one window: Return opens the next page in the window it already
// has, and once that window closes the pane offers to open one again.
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { memoryStorage } from "../../test/render.tsx";
import { browserBridge, type Bridge } from "../bridge.ts";
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
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 1200 });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 800 });
});

describe("a browser pane's window", () => {
  it("is reused for the next page, and offered again once it closes", async () => {
    let closed: (label: string) => void = () => undefined;
    const openBrowserWindow = vi.fn<Bridge["openBrowserWindow"]>(() =>
      Promise.resolve("browser-1"),
    );
    const bridge: Bridge = {
      ...browserBridge({ search: "" }, null),
      openBrowserWindow,
      onBrowserClosed: (callback) => {
        closed = callback;
        return () => undefined;
      },
    };
    const storage = memoryStorage();
    render(
      <DesktopApp
        bridge={bridge}
        api={fakeApi()}
        connect={socketFactory().connect}
        location={{ protocol: "http:", host: "127.0.0.1:8765" }}
        storage={() => storage}
      />,
    );
    await screen.findByRole("button", { name: "Settings" });
    fireEvent.keyDown(document.body, { key: "B", code: "KeyB", ctrlKey: true, shiftKey: true });
    const address = await screen.findByRole("textbox", { name: "Address" });
    const go = async (text: string) => {
      fireEvent.change(address, { target: { value: text } });
      await act(async () => {
        fireEvent.submit(address);
        await Promise.resolve();
      });
    };
    await go("3000");
    expect(openBrowserWindow).toHaveBeenLastCalledWith(
      "http://localhost:3000",
      undefined,
      undefined,
    );
    await go("4000");
    expect(openBrowserWindow).toHaveBeenLastCalledWith(
      "http://localhost:4000",
      undefined,
      "browser-1",
    );
    const pane = within(address.closest<HTMLElement>("section") ?? document.body);
    expect(pane.queryByRole("button", { name: "Open window" })).not.toBeInTheDocument();
    expect(pane.getByRole("button", { name: "Back" })).toBeEnabled();
    act(() => {
      closed("browser-1");
    });
    expect(pane.getByRole("button", { name: "Open window" })).toBeInTheDocument();
    expect(pane.getByRole("button", { name: "Back" })).toBeDisabled();
  });
});
