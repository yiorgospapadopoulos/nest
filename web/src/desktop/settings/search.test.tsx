// As the Mac's Settings (SettingsWindow.swift): the search filters the sidebar's pages and
// leaves the open page where it is.
import { fireEvent, render, screen, within } from "@testing-library/react";
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
});

describe("the settings search", () => {
  it("filters the pages and keeps the open page", async () => {
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
    fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
    const pages = screen.getByRole("navigation", { name: "Settings pages" });
    fireEvent.change(screen.getByRole("textbox", { name: "Search settings" }), {
      target: { value: "island" },
    });
    expect(within(pages).getByRole("button", { name: "Appearance" })).toBeInTheDocument();
    expect(within(pages).queryByRole("button", { name: "General" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "General" })).toBeInTheDocument();
  });
});
