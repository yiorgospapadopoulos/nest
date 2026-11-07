import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import type { SetupCheck } from "../../../api/types.ts";
import { fakeApi } from "../../../test/fakeApi.ts";
import { socketFactory } from "../../../test/fakeSocket.ts";
import { memoryStorage } from "../../../test/render.tsx";
import { browserBridge } from "../../bridge.ts";
import { DesktopApp } from "../../DesktopApp.tsx";

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
});

const tailscale = (stage: string): SetupCheck => ({
  id: "tailscale",
  title: "Tailscale",
  state: "missing",
  message: "Share Nest with your devices.",
  detail: "https://mac.tail1234.ts.net",
  fix: null,
  importance: "optional",
  stage,
  rank: 5,
});

async function pairADevice(stage: string) {
  const api = fakeApi();
  api.setupChecks.mockResolvedValue({ checks: [tailscale(stage)] });
  const storage = memoryStorage();
  render(
    <DesktopApp
      bridge={browserBridge({ search: "" }, null)}
      api={api}
      connect={socketFactory().connect}
      location={{ protocol: "http:", host: "127.0.0.1:41053" }}
      storage={() => storage}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
  const pages = screen.getByRole("navigation", { name: "Settings pages" });
  fireEvent.click(within(pages).getByRole("button", { name: "Devices" }));
  fireEvent.click(await screen.findByRole("button", { name: "Pair a device" }));
  return api;
}

describe("Pair a device", () => {
  // The user's check, 2026-11-07: a code showed with no Tailscale, of no use to the phone.
  it("opens the guide's Tailscale step while Nest is not shared, and makes no code", async () => {
    const api = await pairADevice("share");

    expect(await screen.findByRole("heading", { name: "Pair your iPhone" })).toBeInTheDocument();
    expect(api.pairingCode).not.toHaveBeenCalled();

    // Opened this way, the guide can be left, back to Settings.
    fireEvent.keyDown(window, { key: "Escape" });
    expect(await screen.findByRole("button", { name: "Pair a device" })).toBeInTheDocument();
  });

  it("shows a code once Nest is shared", async () => {
    const api = await pairADevice("pair");

    expect(await screen.findByText("ABCD2345")).toBeInTheDocument();
    expect(api.pairingCode).toHaveBeenCalledOnce();
  });
});
