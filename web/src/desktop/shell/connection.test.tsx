// Regressions (production check, 2026-11-03): with no daemon at launch the window said
// "Nest is not running" for good, without its buttons, a Retry or a way to start the
// service; a daemon lost while running showed only a small "Reconnecting...". As the Mac's
// RootView, the window keeps its frame, shows the banner and recovers by itself.
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { engineUpdates } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { browserBridge, type Bridge, type DaemonConnection } from "../bridge.ts";
import { DesktopRoot } from "../DesktopApp.tsx";

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

afterEach(() => {
  vi.useRealTimers();
});

const DAEMON: DaemonConnection = { base: "http://127.0.0.1:8765", token: "t1" };

function bridgeWith(daemon: () => Promise<DaemonConnection>, extra: Partial<Bridge> = {}) {
  return { ...browserBridge({ search: "" }, null), daemon, ...extra };
}

const flush = async () => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
};

describe("no daemon at launch", () => {
  it("keeps the frame, retries with the Mac's backoff and opens once the daemon answers", async () => {
    vi.useFakeTimers();
    let running = false;
    const daemon = vi.fn(() =>
      running ? Promise.resolve(DAEMON) : Promise.reject(new Error("not running")),
    );
    const api = fakeApi();
    const storage = memoryStorage();
    render(
      <DesktopRoot
        bridge={bridgeWith(daemon)}
        open={() => ({ api, connect: socketFactory().connect })}
        storage={() => storage}
      />,
    );
    await flush();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Reconnecting to the Nest daemon");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Can't reach the Nest daemon. Trying again in 1s",
    );
    running = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    vi.useRealTimers();
    expect(await screen.findByRole("button", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("starts the service, or shows how to install it when it is missing", async () => {
    vi.useFakeTimers();
    let running = false;
    const startService = vi.fn(() => Promise.resolve("not_installed" as const));
    const bridge = bridgeWith(
      () => (running ? Promise.resolve(DAEMON) : Promise.reject(new Error("not running"))),
      { startService },
    );
    const api = fakeApi();
    render(
      <DesktopRoot
        bridge={bridge}
        open={() => ({ api, connect: socketFactory().connect })}
        storage={memoryStorage}
      />,
    );
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Start Nest service" }));
    await flush();
    expect(
      screen.getByText("cd <your Nest checkout>/daemon && uv run nestd service install"),
    ).toBeInTheDocument();
    startService.mockResolvedValue("started" as never);
    running = true;
    fireEvent.click(screen.getByRole("button", { name: "Start Nest service" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    vi.useRealTimers();
    expect(await screen.findByRole("button", { name: "Settings" })).toBeInTheDocument();
  });
});

// Regression (production check, 2026-11-03): a new chat's unsent text came back after a
// relaunch, kept on the device by the shared store. As the Mac's DraftBook, it lives only
// while the app runs.
describe("a relaunch", () => {
  it("starts with no unsent text from before", async () => {
    const storage = memoryStorage();
    storage.setItem(
      "nest.drafts",
      JSON.stringify({ "new:todo-ui": { text: "an old idea", files: [] } }),
    );
    render(
      <DesktopRoot
        bridge={bridgeWith(() => Promise.resolve(DAEMON))}
        open={() => ({ api: fakeApi(), connect: socketFactory().connect })}
        storage={() => storage}
      />,
    );
    await screen.findByRole("button", { name: "Settings" });
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    const pane = await screen.findByRole("region", { name: "New chat" });
    expect(within(pane).getByRole("textbox", { name: "Message" })).toHaveValue("");
  });
});

describe("a daemon lost while running", () => {
  it("warns of nothing during a relaunch this app asked for", async () => {
    const sockets = socketFactory();
    const api = fakeApi();
    api.checkUpdates.mockResolvedValue(
      engineUpdates({
        state: "ready",
        engines: [{ id: "claude", name: "Claude Code", current: "2.1.317", new: "2.1.318" }],
      }),
    );
    render(
      <DesktopRoot
        bridge={bridgeWith(() => Promise.resolve(DAEMON))}
        open={() => ({ api, connect: sockets.connect })}
        storage={memoryStorage}
      />,
    );
    const relaunch = await screen.findByRole("button", { name: "Relaunch to update" });
    act(() => {
      sockets.last().open();
    });
    fireEvent.click(relaunch);
    await screen.findByRole("button", { name: "Relaunching..." });

    act(() => {
      sockets.last().drop(1006);
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the banner with Retry and recovers when the daemon answers", async () => {
    const api = fakeApi();
    const sockets = socketFactory();
    render(
      <DesktopRoot
        bridge={bridgeWith(() => Promise.resolve(DAEMON))}
        open={() => ({ api, connect: sockets.connect })}
        storage={memoryStorage}
      />,
    );
    await screen.findByRole("button", { name: "Settings" });
    vi.useFakeTimers();
    api.health.mockRejectedValue(new TypeError("Failed to fetch"));
    act(() => {
      sockets.last().drop(1006);
    });
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent("Reconnecting to the Nest daemon");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Trying again in 1s");
    expect(screen.getByRole("button", { name: "Start Nest service" })).toBeInTheDocument();
    // A refusal still means it answers.
    api.health.mockRejectedValue(new ApiError(401, "no"));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await flush();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
