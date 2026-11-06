import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { fakeApi } from "../../../test/fakeApi.ts";
import { socketFactory } from "../../../test/fakeSocket.ts";
import { memoryStorage } from "../../../test/render.tsx";
import { browserBridge } from "../../bridge.ts";
import { DesktopApp } from "../../DesktopApp.tsx";

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

describe("Pixies and subagents can push", () => {
  it("shows the saved value and saves a change", async () => {
    const api = fakeApi();
    api.limitSettings.mockResolvedValue({ can_push: true });
    const storage = memoryStorage();
    render(
      <DesktopApp
        bridge={browserBridge({ search: "" }, null)}
        api={api}
        connect={socketFactory().connect}
        location={{ protocol: "http:", host: "127.0.0.1:8765" }}
        storage={() => storage}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
    const pages = screen.getByRole("navigation", { name: "Settings pages" });
    fireEvent.click(within(pages).getByRole("button", { name: "Pixies" }));

    const toggle = () => screen.getByRole("switch", { name: "Pixies and subagents can push" });
    await waitFor(() => {
      expect(toggle()).toBeChecked();
    });
    fireEvent.click(toggle());

    expect(api.saveLimitSettings).toHaveBeenLastCalledWith({ can_push: false });
    await waitFor(() => {
      expect(toggle()).not.toBeChecked();
    });
  });
});
