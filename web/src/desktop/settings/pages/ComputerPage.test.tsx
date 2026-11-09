// Settings > Computer use (B150) on the desktop: saves, and a blocked permission says so
// with Open.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import type { ComputerStatus } from "../../../api/types.ts";
import { fakeApi, type FakeApi } from "../../../test/fakeApi.ts";
import { socketFactory } from "../../../test/fakeSocket.ts";
import { memoryStorage } from "../../../test/render.tsx";
import { browserBridge } from "../../bridge.ts";
import { DesktopApp } from "../../DesktopApp.tsx";

const BLOCKED: ComputerStatus = {
  enabled: true,
  kinds: [
    { kind: "mac", ready: true, reason: null, link: null },
    {
      kind: "android",
      ready: false,
      reason: "Android Studio is not installed.",
      link: "https://developer.android.com/studio",
    },
  ],
  accessibility: true,
  screen_recording: false,
};

function blockedApi(): FakeApi {
  const api = fakeApi();
  api.computerSettings.mockResolvedValue({
    enabled: true,
    pixies: false,
  });
  api.computerStatus.mockResolvedValue(BLOCKED);
  return api;
}

beforeAll(() => {
  // jsdom has none; the desktop workspace measures itself with one.
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

describe("Settings > Computer use (B150)", () => {
  it("saves the master switch and opens a blocked permission", async () => {
    const api = blockedApi();
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
    fireEvent.click(within(pages).getByRole("button", { name: "Computer use" }));

    expect(await screen.findByText("Blocked in System Settings.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Open Screen Recording for Nest/ }));
    expect(api.askComputerPermission).toHaveBeenCalledWith("screen_recording");

    const master = screen.getByRole("switch", { name: "Let chats use apps" });
    await waitFor(() => {
      expect(master).toBeChecked();
    });
    fireEvent.click(master);
    expect(api.saveComputerSettings).toHaveBeenLastCalledWith({
      enabled: false,
      pixies: false,
    });
  });
});
