import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { SetupCheck } from "../../api/types.ts";
import { engineAccount } from "../../test/accounts.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { acpProvider, claudeProvider, engineUpdates } from "../../test/fixtures.ts";
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

const check = (id: string, overrides: Partial<SetupCheck> = {}): SetupCheck => ({
  id,
  title: id,
  state: "missing",
  message: "",
  detail: null,
  fix: null,
  importance: "recommended",
  stage: null,
  rank: 1,
  ...overrides,
});

function renderGuide(api = fakeApi(), bridge: Partial<Bridge> = {}) {
  const storage = memoryStorage();
  render(
    <DesktopApp
      bridge={{ ...browserBridge({ search: "" }, null), ...bridge }}
      api={api}
      connect={socketFactory().connect}
      location={{ protocol: "http:", host: "127.0.0.1:41053" }}
      storage={() => storage}
    />,
  );
  return { api, user: userEvent.setup() };
}

function firstRun(checks: SetupCheck[]) {
  const api = fakeApi();
  api.setup.mockResolvedValue({ first_run: true, local_only: false });
  api.setupChecks.mockResolvedValue({ checks });
  return api;
}

describe("the setup guide on a new install", () => {
  it("holds at the engine step, with no way past it, until an engine is signed in", async () => {
    const api = firstRun([check("engine")]);
    const { user } = renderGuide(api);
    await screen.findByRole("heading", { name: "Sign in to an engine" });

    expect(screen.queryByRole("button", { name: "Skip" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();

    const rail = screen.getByRole("navigation", { name: "Set up Nest" });
    await user.click(within(rail).getByRole("button", { name: /First chat/ }));

    expect(screen.getByRole("button", { name: "Finish" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Open a chat" })).toBeDisabled();
    expect(api.finishSetup).not.toHaveBeenCalled();
  });

  it("opens the other engines in the step itself, and one ready there lets it go on", async () => {
    const api = firstRun([check("engine")]);
    const opencode = acpProvider({ signed_in: false });
    api.providers.mockResolvedValue({ providers: [claudeProvider(), opencode] });
    const { user } = renderGuide(api);
    await screen.findByRole("heading", { name: "Sign in to an engine" });
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();

    await user.click(await screen.findByRole("button", { name: /Show/ }));
    const more = screen.getByRole("group", { name: "More engines" });
    expect(within(more).getByRole("button", { name: "Copy sign-in command" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Sign in to an engine" })).toBeInTheDocument();

    // Signed in from its terminal: the engines are asked again on the way back.
    api.providers.mockResolvedValue({
      providers: [claudeProvider(), { ...opencode, signed_in: true }],
    });
    window.dispatchEvent(new Event("focus"));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
    });
  });

  it("re-reads the checks after Use local models only and stays in the guide", async () => {
    const api = firstRun([check("engine")]);
    const { user } = renderGuide(api);
    await screen.findByRole("heading", { name: "Sign in to an engine" });
    api.setupChecks.mockResolvedValue({ checks: [check("engine", { state: "ok" })] });

    await user.click(screen.getByRole("button", { name: "Use local models only" }));

    expect(api.useLocalOnly).toHaveBeenCalledOnce();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
    });
    expect(screen.getByRole("heading", { name: "Sign in to an engine" })).toBeInTheDocument();
  });

  it("marks a skipped step, and Finish ends it for good", async () => {
    const api = firstRun([
      check("engine", { state: "ok" }),
      check("git", { message: "git is missing." }),
      check("first_chat"),
    ]);
    const { user } = renderGuide(api);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("git is missing.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Skip" }));

    const rail = screen.getByRole("navigation", { name: "Set up Nest" });
    expect(within(rail).getByRole("button", { name: /Skipped\s*git/ })).toBeInTheDocument();

    await user.click(within(rail).getByRole("button", { name: /First chat/ }));
    await user.click(screen.getByRole("button", { name: "Finish" }));

    expect(api.finishSetup).toHaveBeenCalledOnce();
    expect(await screen.findByRole("button", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Set up Nest" })).not.toBeInTheDocument();
  });

  it("opens the first chat on the cheapest model of the engine signed in", async () => {
    const api = firstRun([check("engine", { state: "ok" })]);
    api.accounts.mockResolvedValue({ accounts: [engineAccount()] });
    const { user } = renderGuide(api);
    const rail = await screen.findByRole("navigation", { name: "Set up Nest" });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
    });
    await user.click(within(rail).getByRole("button", { name: /First chat/ }));
    await user.click(screen.getByRole("button", { name: "Open a chat" }));

    expect(api.finishSetup).toHaveBeenCalledOnce();
    await user.type(await screen.findByRole("textbox", { name: "Message" }), "Hello{Enter}");
    await waitFor(() => {
      expect(api.createSession).toHaveBeenCalled();
    });
    expect(api.createSession.mock.calls[0]?.[0]).toMatchObject({
      repo: "general",
      provider: "claude",
      model: "haiku",
    });
  });
});

// Regression (B130, fix 28): at first start the projects showed for a moment before the
// guide, until the daemon said it was a first run.
describe("the window at first start", () => {
  it("stays blank until it knows, and never shows the projects before the guide", async () => {
    const api = firstRun([check("engine")]);
    let answer: (setup: { first_run: boolean; local_only: boolean }) => void = () => undefined;
    api.setup.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    renderGuide(api);
    await waitFor(() => {
      expect(api.setup).toHaveBeenCalled();
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("button", { name: "Settings" })).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Set up Nest" })).not.toBeInTheDocument();

    answer({ first_run: true, local_only: false });
    expect(await screen.findByRole("navigation", { name: "Set up Nest" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Settings" })).not.toBeInTheDocument();
  });
});

describe("the guide's steps", () => {
  it("names GitHub's link Download", async () => {
    const api = firstRun([
      check("engine", { state: "ok" }),
      check("github", { fix: { kind: "link", value: "https://cli.github.com" } }),
    ]);
    const { user } = renderGuide(api);
    const rail = await screen.findByRole("navigation", { name: "Set up Nest" });
    await user.click(within(rail).getByRole("button", { name: /GitHub/ }));
    expect(await screen.findByRole("button", { name: "Download" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open" })).not.toBeInTheDocument();
  });

  it("shows each way a notification arrives as a switch in its real state", async () => {
    const api = firstRun([check("engine", { state: "ok" })]);
    api.pushStatus.mockResolvedValue({ devices: 1 });
    const { user } = renderGuide(api, { notificationServer: () => Promise.resolve(null) });
    const rail = await screen.findByRole("navigation", { name: "Set up Nest" });
    await user.click(within(rail).getByRole("button", { name: /Notifications/ }));

    expect(await screen.findByText("No notification service answers.")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "This computer's notifications" })).not.toBeChecked();
    await waitFor(() => {
      expect(screen.getByRole("switch", { name: "iPhone notifications" })).toBeChecked();
    });
    // ntfy is in Settings only (B130).
    expect(screen.queryByRole("switch", { name: "Send to ntfy" })).not.toBeInTheDocument();
  });
});

describe("the app swap", () => {
  const FILE = { version: "0.2.0", path: "/data/daemon/0.2.0/app-file" };

  it("happens once a launch, however often the daemon says so", async () => {
    const api = fakeApi();
    api.updates.mockResolvedValue(engineUpdates({ app_file: FILE }));
    api.checkUpdates.mockResolvedValue(engineUpdates({ app_file: FILE }));
    const swapApp = vi.fn(() => Promise.resolve());
    renderGuide(api, { appVersion: () => Promise.resolve("0.1.0"), swapApp });
    await waitFor(() => {
      expect(swapApp).toHaveBeenCalledWith(FILE.path);
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(swapApp).toHaveBeenCalledOnce();
  });

  it("leaves an app of the daemon's version alone, and a dev build", async () => {
    const api = fakeApi();
    api.updates.mockResolvedValue(engineUpdates({ app_file: FILE }));
    api.checkUpdates.mockResolvedValue(engineUpdates({ app_file: FILE }));
    const appVersion = vi.fn(() => Promise.resolve<string | null>("0.2.0"));
    const swapApp = vi.fn(() => Promise.resolve());
    renderGuide(api, { appVersion, swapApp });
    await waitFor(() => {
      expect(appVersion).toHaveBeenCalled();
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(swapApp).not.toHaveBeenCalled();
  });
});
