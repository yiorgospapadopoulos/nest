// Regression (VM, 2026-11-03): Escape sent to the window with nothing focused left the
// Settings open. As on the Mac, Escape closes the topmost overlay wherever the
// keyboard focus is.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { memoryStorage } from "../../test/render.tsx";
import { browserBridge } from "../bridge.ts";
import { DesktopApp } from "../DesktopApp.tsx";

beforeAll(() => {
  // jsdom has none; the workspace measures itself with one.
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
  // Nor this, which the palette calls to keep its selection in view.
  Element.prototype.scrollIntoView = () => undefined;
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

const escapeOnTheWindow = () => {
  act(() => {
    (document.activeElement as HTMLElement | null)?.blur();
  });
  fireEvent.keyDown(document.body, { key: "Escape" });
};

describe("Escape", () => {
  it("closes Settings opened from the status bar with nothing focused", async () => {
    await renderDesktop();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("region", { name: "Settings" })).toBeInTheDocument();
    escapeOnTheWindow();
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Settings" })).not.toBeInTheDocument();
    });
  });

  it("closes Settings from inside it, and the palette, one at a time", async () => {
    await renderDesktop();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Search settings" }), {
      key: "Escape",
    });
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Settings" })).not.toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /^Search/ }));
    expect(screen.getByRole("dialog", { name: "Search chats and commands" })).toBeInTheDocument();
    escapeOnTheWindow();
    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "Search chats and commands" }),
      ).not.toBeInTheDocument();
    });
  });
});
