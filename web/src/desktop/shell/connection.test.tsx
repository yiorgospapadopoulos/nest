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
    expect(screen.getByText("Connecting to Nest")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(
      screen.getByRole("heading", { name: "Nest's background service isn't running" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/releases\/latest\/download\/install\.sh \| sh/)).toBeInTheDocument();
    running = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    vi.useRealTimers();
    expect(await screen.findByRole("button", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says what stops the daemon when the app can tell", async () => {
    vi.useFakeTimers();
    const api = fakeApi();
    const bridge = bridgeWith(() => Promise.reject(new Error("not running")), {
      daemonProblem: () => Promise.resolve("Install gnome-keyring."),
    });
    render(
      <DesktopRoot
        bridge={bridge}
        open={() => ({ api, connect: socketFactory().connect })}
        storage={memoryStorage}
      />,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(screen.getByRole("heading", { name: "Nest can't start" })).toBeInTheDocument();
    expect(screen.getByText("Install gnome-keyring.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy" })).not.toBeInTheDocument();
  });

  // Regression (the user's test run, 2026-11-07): the screen asked to install again for a
  // service Nest can start itself, with GitHub's address for an install from elsewhere.
  it("starts the service once by itself, then shows the line from the install's address", async () => {
    vi.useFakeTimers();
    let running = false;
    const startService = vi.fn(() => Promise.resolve("started" as const));
    const url = "http://192.168.64.1:41051";
    const bridge = bridgeWith(
      () => (running ? Promise.resolve(DAEMON) : Promise.reject(new Error("not running"))),
      {
        startService,
        installState: () => Promise.resolve({ updating: null, releaseUrl: url, released: true }),
      },
    );
    render(
      <DesktopRoot
        bridge={bridge}
        open={() => ({ api: fakeApi(), connect: socketFactory().connect })}
        storage={memoryStorage}
      />,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(startService).toHaveBeenCalledOnce();
    expect(screen.getByText("Connecting to Nest")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(
      screen.getByRole("heading", { name: "Nest's background service isn't running" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(`curl -fsSL ${url}/install.sh | NEST_RELEASE_URL=${url} sh`),
    ).toBeInTheDocument();
    expect(startService).toHaveBeenCalledOnce();

    startService.mockImplementation(() => {
      running = true;
      return Promise.resolve("started" as const);
    });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(startService).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    vi.useRealTimers();
    expect(await screen.findByRole("button", { name: "Settings" })).toBeInTheDocument();
  });

  it("never shows the screen when starting the service brings Nest back", async () => {
    vi.useFakeTimers();
    let running = false;
    const startService = vi.fn(() => {
      running = true;
      return Promise.resolve("started" as const);
    });
    const bridge = bridgeWith(
      () => (running ? Promise.resolve(DAEMON) : Promise.reject(new Error("not running"))),
      { startService },
    );
    render(
      <DesktopRoot
        bridge={bridge}
        open={() => ({ api: fakeApi(), connect: socketFactory().connect })}
        storage={memoryStorage}
      />,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    vi.useRealTimers();
    expect(await screen.findByRole("button", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /isn't running/ })).not.toBeInTheDocument();
  });
});

// Regression (the user's test run, 2026-11-07): during an update the daemon-down screen
// asked to install again, while the watcher was still bringing the new version up.
describe("the daemon down for an update", () => {
  it("shows the update, then that it is slow, and never the repair line", async () => {
    vi.useFakeTimers();
    let running = false;
    const startService = vi.fn(() => Promise.resolve("started" as const));
    const updating = {
      from_version: "0.1.0",
      to_version: "0.2.0",
      started_at: new Date(Date.now()).toISOString().replace("Z", "123+00:00"),
    };
    const bridge = bridgeWith(
      () => (running ? Promise.resolve(DAEMON) : Promise.reject(new Error("not running"))),
      {
        startService,
        installState: () =>
          Promise.resolve({ updating, releaseUrl: "https://example.com", released: true }),
      },
    );
    render(
      <DesktopRoot
        bridge={bridge}
        open={() => ({ api: fakeApi(), connect: socketFactory().connect })}
        storage={memoryStorage}
      />,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByRole("heading", { name: "Updating Nest to 0.2.0..." })).toBeInTheDocument();
    // Regression (B130, fix 30b): the line's place is kept from the start, so the screen
    // does not move when it appears.
    expect(screen.getByText("Taking longer than usual")).not.toBeVisible();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(13_000);
    });
    expect(screen.getByText("Taking longer than usual")).toBeVisible();
    expect(screen.queryByText(/install\.sh/)).not.toBeInTheDocument();
    expect(startService).not.toHaveBeenCalled();

    running = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    vi.useRealTimers();
    expect(await screen.findByRole("button", { name: "Settings" })).toBeInTheDocument();
  });
});

// Regression (B130, fix 27): on the Mac the updating screen flickered out and back as each
// try passed through a state taken for "no update", which also started the service
// mid-update. Here no try, not even one whose read of the update fails, leaves the screen.
describe("the update's screen", () => {
  it("holds through every try until the daemon is back", async () => {
    vi.useFakeTimers();
    let running = false;
    let reads = 0;
    const startService = vi.fn(() => Promise.resolve("started" as const));
    const updating = {
      from_version: "0.1.0",
      to_version: "0.2.0",
      started_at: new Date(Date.now()).toISOString(),
    };
    const bridge = bridgeWith(
      () => (running ? Promise.resolve(DAEMON) : Promise.reject(new Error("not running"))),
      {
        startService,
        installState: () => {
          reads += 1;
          return reads % 3 === 0
            ? Promise.reject(new Error("busy"))
            : Promise.resolve({ updating, releaseUrl: "https://example.com", released: true });
        },
      },
    );
    render(
      <DesktopRoot
        bridge={bridge}
        open={() => ({ api: fakeApi(), connect: socketFactory().connect })}
        storage={memoryStorage}
      />,
    );
    await flush();
    for (let tick = 0; tick < 40; tick += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(250);
      });
      expect(
        screen.getByRole("heading", { name: "Updating Nest to 0.2.0..." }),
      ).toBeInTheDocument();
      expect(screen.queryByText("Connecting to Nest")).not.toBeInTheDocument();
    }
    expect(reads).toBeGreaterThan(6);
    expect(startService).not.toHaveBeenCalled();

    running = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    vi.useRealTimers();
    expect(await screen.findByRole("button", { name: "Settings" })).toBeInTheDocument();
  });
});

const INSTALL = { releaseUrl: "https://example.com", released: true };
const UPDATING = { from_version: "0.1.0", to_version: "0.2.0" };

describe("an update at launch", () => {
  // Regression (B130, fix 30a): the window showed Connecting until a first try failed.
  // `update.json` is read before the first try, so the update shows while it is pending.
  it("shows the Updating screen before the first try ends", async () => {
    vi.useFakeTimers();
    const updating = { ...UPDATING, started_at: new Date(Date.now()).toISOString() };
    const bridge = bridgeWith(() => new Promise<DaemonConnection>(() => undefined), {
      installState: () => Promise.resolve({ updating, ...INSTALL }),
    });
    render(
      <DesktopRoot
        bridge={bridge}
        open={() => ({ api: fakeApi(), connect: socketFactory().connect })}
        storage={memoryStorage}
      />,
    );
    await flush();
    expect(screen.getByRole("heading", { name: "Updating Nest to 0.2.0..." })).toBeInTheDocument();
    expect(screen.queryByText("Connecting to Nest")).not.toBeInTheDocument();
  });

  // Regression (B130, fix 30b): going back, the watcher clears `update.json` before the old
  // version answers, and the screen gave way to the window, which started the service
  // mid-rollback. It stays until the daemon answers, for up to 30 seconds.
  it("keeps the Updating screen a while after update.json clears", async () => {
    vi.useFakeTimers();
    let updating: (typeof UPDATING & { started_at: string }) | null = {
      ...UPDATING,
      started_at: new Date(Date.now()).toISOString(),
    };
    const startService = vi.fn(() => Promise.resolve("started" as const));
    const bridge = bridgeWith(() => Promise.reject(new Error("not running")), {
      startService,
      installState: () => Promise.resolve({ updating, ...INSTALL }),
    });
    render(
      <DesktopRoot
        bridge={bridge}
        open={() => ({ api: fakeApi(), connect: socketFactory().connect })}
        storage={memoryStorage}
      />,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    updating = null;
    for (let second = 0; second < 28; second += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(
        screen.getByRole("heading", { name: "Updating Nest to 0.2.0..." }),
      ).toBeInTheDocument();
    }
    expect(startService).not.toHaveBeenCalled();

    // Still not back: the service starts once, as at launch.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.queryByRole("heading", { name: /Updating Nest/ })).not.toBeInTheDocument();
    expect(startService).toHaveBeenCalledOnce();
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

  // Regression (the user's test run, 2026-11-07): with a new app in the update, the old app
  // loaded again after the daemon's restart, only to quit for the swap.
  it("hands a relaunch with a new app to the helper that opens it once", async () => {
    const api = fakeApi();
    api.checkUpdates.mockResolvedValue(
      engineUpdates({ state: "ready", app: { version: "0.2.0", notes: "" } }),
    );
    const relaunchApp = vi.fn(() => Promise.resolve(true));
    render(
      <DesktopRoot
        bridge={bridgeWith(() => Promise.resolve(DAEMON), { relaunchApp })}
        open={() => ({ api, connect: socketFactory().connect })}
        storage={memoryStorage}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Relaunch to update" }));

    await vi.waitFor(() => {
      expect(relaunchApp).toHaveBeenCalledWith("0.2.0");
    });
    expect(api.relaunchUpdate).toHaveBeenCalledOnce();
    expect(api.relaunchUpdate.mock.invocationCallOrder[0]).toBeLessThan(
      relaunchApp.mock.invocationCallOrder[0] ?? 0,
    );
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
