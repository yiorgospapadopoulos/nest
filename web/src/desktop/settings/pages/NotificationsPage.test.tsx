import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { fakeApi } from "../../../test/fakeApi.ts";
import { socketFactory } from "../../../test/fakeSocket.ts";
import { notificationSettings } from "../../../test/fixtures.ts";
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

async function openNotifications(api = fakeApi()) {
  const storage = memoryStorage();
  render(
    <DesktopApp
      bridge={{ ...browserBridge({ search: "" }, null), native: true }}
      api={api}
      connect={socketFactory().connect}
      location={{ protocol: "http:", host: "127.0.0.1:41053" }}
      storage={() => storage}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
  const pages = screen.getByRole("navigation", { name: "Settings pages" });
  fireEvent.click(within(pages).getByRole("button", { name: "Notifications" }));
  return await screen.findByRole("switch", { name: "Send to ntfy" });
}

const savedNtfy = (api: ReturnType<typeof fakeApi>) =>
  api.saveNotificationSettings.mock.calls.at(-1)?.[0].ntfy;

describe("ntfy in Settings", () => {
  // The daemon refuses ntfy on with no topic, and a short or guessable one is readable by
  // anyone (B130).
  it("turns on with a long random topic, and its fields open only while on", async () => {
    const api = fakeApi();
    const ntfy = await openNotifications(api);
    expect(screen.queryByRole("textbox", { name: "Topic" })).not.toBeInTheDocument();

    fireEvent.click(ntfy);
    await waitFor(() => {
      expect(api.saveNotificationSettings).toHaveBeenCalledOnce();
    });
    const saved = savedNtfy(api);
    expect(saved?.enabled).toBe(true);
    expect(saved?.topic).toMatch(/^[A-Za-z0-9]{32}$/);
    const topic = await screen.findByRole("textbox", { name: "Topic" });
    expect(topic).toHaveValue(saved?.topic);
    expect(screen.getByText(/Anyone who knows a public topic/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Send to ntfy" }));
    await waitFor(() => {
      expect(screen.queryByRole("textbox", { name: "Topic" })).not.toBeInTheDocument();
    });
    expect(savedNtfy(api)).toMatchObject({ enabled: false, topic: saved?.topic });
  });

  it("keeps a topic already there", async () => {
    const api = fakeApi();
    const rules = notificationSettings();
    api.notificationSettings.mockResolvedValue({
      ...rules,
      ntfy: { ...rules.ntfy, topic: "my-own-topic-1234" },
    });
    fireEvent.click(await openNotifications(api));
    await waitFor(() => {
      expect(savedNtfy(api)).toMatchObject({ enabled: true, topic: "my-own-topic-1234" });
    });
  });
});
