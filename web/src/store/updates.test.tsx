import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client.ts";
import { UPDATES_CHANGED } from "../api/events.ts";
import type { EngineUpdates, JsonObject } from "../api/types.ts";
import { fakeApi } from "../test/fakeApi.ts";
import { engineUpdates, session } from "../test/fixtures.ts";
import { renderApp } from "../test/render.tsx";
import { RESTART_POLL_MS, RESTART_POLLS } from "./actions.ts";

const READY = engineUpdates({
  state: "ready",
  engines: [{ id: "claude", name: "Claude Code", current: "2.1.317", new: "2.1.318" }],
});

const relaunchButton = () => screen.findByRole("button", { name: "Relaunch to update" });
const strip = () => screen.queryByRole("button", { name: "What's updating" });

function changed(status: EngineUpdates) {
  return { type: UPDATES_CHANGED, id: null, payload: status as unknown as JsonObject };
}

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe = vi.fn();
      disconnect = vi.fn();
    },
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** Clicks with fake timers, so the waits between the daemon's checks are in the test's hands. */
async function clickWithTimers(button: HTMLElement) {
  const reload = vi.fn();
  vi.stubGlobal("location", { pathname: window.location.pathname, reload });
  vi.useFakeTimers();
  fireEvent.click(button);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  return reload;
}

const wait = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

describe("engine updates", () => {
  it("checks once when the app opens and reads the state on every connect", async () => {
    const { api, sockets } = await renderApp();
    act(() => {
      sockets.last().open();
    });
    await waitFor(() => {
      expect(api.updates).toHaveBeenCalledOnce();
    });

    sockets.reconnect();
    sockets.reconnect();

    await waitFor(() => {
      expect(api.updates).toHaveBeenCalledTimes(3);
    });
    expect(api.checkUpdates).toHaveBeenCalledOnce();
  });

  it.each(["none", "checking", "preparing"] as const)("shows nothing while %s", async (state) => {
    const { push } = await renderApp();
    push(changed(engineUpdates({ state })));
    expect(strip()).not.toBeInTheDocument();
  });

  it("shows the engines' versions from the strip's toggle", async () => {
    const { push, user } = await renderApp();
    push(changed(READY));
    await user.click(screen.getByRole("button", { name: "What's updating" }));
    expect(screen.getByText("Claude Code 2.1.317 → 2.1.318")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "What's updating" }));
    expect(screen.queryByText("Claude Code 2.1.317 → 2.1.318")).not.toBeInTheDocument();
  });

  it("hides the strip across a reconnect, but not the row, until a fresh load", async () => {
    const api = fakeApi();
    api.checkUpdates.mockResolvedValue(READY);
    api.updates.mockResolvedValue(READY);
    const { push, sockets, user, unmount } = await renderApp({ api });

    await user.click(await screen.findByRole("button", { name: "Hide for now" }));
    expect(strip()).not.toBeInTheDocument();
    expect(api.dismissUpdateNotice).not.toHaveBeenCalled();

    sockets.reconnect();
    push(changed(READY));
    await waitFor(() => {
      expect(api.updates).toHaveBeenCalledTimes(1);
    });
    expect(strip()).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Settings" }));
    await user.click(await screen.findByRole("button", { name: /^General/ }));
    expect(await screen.findByText("Update available")).toBeInTheDocument();

    unmount();
    await renderApp({ api });
    await waitFor(() => {
      expect(strip()).toBeInTheDocument();
    });
  });

  it("offers the phone no app update, alone or beside the engines", async () => {
    const app = { version: "0.2.0", notes: "Better." };
    const { push, user } = await renderApp();
    push(changed(engineUpdates({ state: "ready", app })));
    expect(strip()).not.toBeInTheDocument();

    push(changed({ ...READY, app }));
    await user.click(screen.getByRole("button", { name: "What's updating" }));
    expect(screen.getByText("Claude Code 2.1.317 → 2.1.318")).toBeInTheDocument();
    expect(screen.queryByText(/Nest 0\.2\.0/)).not.toBeInTheDocument();
  });

  it("keeps a notice showing after the strip was hidden", async () => {
    const { push, user } = await renderApp();
    push(changed(READY));
    await user.click(screen.getByRole("button", { name: "Hide for now" }));
    push(changed({ ...READY, notice: "Went back to the engines from before." }));
    expect(screen.getByText("Went back to the engines from before.")).toBeInTheDocument();
  });

  it("stays out of an open chat, where the composer is", async () => {
    const api = fakeApi();
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [session()]));
    api.checkUpdates.mockResolvedValue(READY);
    const { user } = await renderApp({ api });
    await relaunchButton();
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: /^.+,/ }));
    expect(strip()).not.toBeInTheDocument();
  });

  it("lets a notice win over a ready update until it is dismissed", async () => {
    const api = fakeApi();
    api.dismissUpdateNotice.mockResolvedValue(READY);
    const { push, user } = await renderApp({ api });
    push(changed({ ...READY, notice: "Went back to the engines from before." }));

    expect(screen.getByText("Went back to the engines from before.")).toBeInTheDocument();
    expect(strip()).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(api.dismissUpdateNotice).toHaveBeenCalledOnce();
    expect(await relaunchButton()).toBeInTheDocument();
  });

  it("relaunches at once with no chat mid-turn, and reloads once the daemon is back", async () => {
    const api = fakeApi();
    api.checkUpdates.mockResolvedValue(READY);
    api.updates.mockResolvedValue(READY);
    const { push, sockets } = await renderApp({ api });
    const button = await relaunchButton();
    api.health.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const reload = await clickWithTimers(button);
    await wait(0);
    expect(api.relaunchUpdate).toHaveBeenCalledOnce();

    // The daemon drops what is ready as soon as it agrees, before it goes away.
    push(changed(engineUpdates({ can_undo: true })));
    expect(screen.getByRole("button", { name: "Relaunching..." })).toBeDisabled();

    // The socket can be back before the page reloads: nothing changes until it does.
    await wait(RESTART_POLL_MS);
    expect(reload).not.toHaveBeenCalled();
    sockets.reconnect();
    await wait(0);
    expect(screen.getByRole("button", { name: "Relaunching..." })).toBeDisabled();

    await wait(RESTART_POLL_MS);
    expect(reload).toHaveBeenCalledOnce();
  });

  it("says so and gives the button back when the daemon does not come back", async () => {
    const api = fakeApi();
    api.checkUpdates.mockResolvedValue(READY);
    api.updates.mockResolvedValue(READY);
    const { sockets } = await renderApp({ api });
    const button = await relaunchButton();
    api.health.mockRejectedValue(new TypeError("Failed to fetch"));
    const reload = await clickWithTimers(button);
    await wait(0);
    sockets.last().drop(1006);

    await wait(RESTART_POLL_MS * RESTART_POLLS);

    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByText("Nest did not come back.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Relaunch to update" })).toBeEnabled();
    expect(screen.getByText("Reconnecting...")).toBeInTheDocument();
  });

  it("shows no reconnecting note during a restart it asked for, and does after", async () => {
    const api = fakeApi();
    api.checkUpdates.mockResolvedValue(READY);
    api.updates.mockResolvedValue(READY);
    const { sockets } = await renderApp({ api });
    const button = await relaunchButton();
    api.health.mockRejectedValue(new TypeError("Failed to fetch"));
    await clickWithTimers(button);
    await wait(0);

    act(() => {
      sockets.last().drop(1006);
    });

    expect(screen.queryByText("Reconnecting...")).not.toBeInTheDocument();
  });

  it("offers the update in Settings even with a notice up, and relaunches from there", async () => {
    const api = fakeApi();
    const notice = {
      ...READY,
      engines: [...READY.engines, { id: "codex", name: "Codex", current: "0.10.0", new: "0.11.0" }],
      notice: "Went back to the engines from before.",
    };
    api.checkUpdates.mockResolvedValue(notice);
    api.updates.mockResolvedValue({ ...notice, busy_chats: 1 });
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Settings" }));
    await user.click(await screen.findByRole("button", { name: /^General/ }));

    expect(await screen.findByText("Update available")).toBeInTheDocument();
    expect(screen.getByText(/Claude Code 2\.1\.317 → 2\.1\.318\s+Codex/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Relaunch to update" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("1 chat is mid-turn");
    expect(api.relaunchUpdate).not.toHaveBeenCalled();
  });

  it("shows Settings' row only while an update is ready", async () => {
    const api = fakeApi();
    const { push, user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Settings" }));
    await user.click(await screen.findByRole("button", { name: /^General/ }));
    await screen.findByText("Restart Nest");
    expect(screen.queryByText("Update available")).not.toBeInTheDocument();

    push(changed(READY));
    expect(screen.getByText("Update available")).toBeInTheDocument();
  });

  it("gives the button back when the relaunch is refused", async () => {
    const api = fakeApi();
    api.checkUpdates.mockResolvedValue(READY);
    api.updates.mockResolvedValue(READY);
    api.relaunchUpdate.mockRejectedValue(new ApiError(409, "No update is ready"));
    const { user } = await renderApp({ api });

    await user.click(await relaunchButton());

    expect(await relaunchButton()).toBeEnabled();
    expect(await screen.findByText("No update is ready")).toBeInTheDocument();
  });

  it("asks before stopping chats mid-turn, going by the count now, not the last event", async () => {
    const api = fakeApi();
    const { push, user } = await renderApp({ api });
    push(changed(READY));
    // Two turns started since: `updates.changed` does not follow those.
    api.updates.mockResolvedValue({ ...READY, busy_chats: 2 });

    await user.click(await relaunchButton());

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("2 chats are mid-turn");
    expect(api.relaunchUpdate).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(api.relaunchUpdate).not.toHaveBeenCalled();

    await user.click(await relaunchButton());
    await user.click(await screen.findByRole("button", { name: "Relaunch" }));
    expect(api.relaunchUpdate).toHaveBeenCalledOnce();
  });

  it("offers Undo only when there is something to go back to, and confirms first", async () => {
    const api = fakeApi();
    const { push, user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Settings" }));
    await user.click(await screen.findByRole("button", { name: /^General/ }));
    await screen.findByText("Restart Nest");
    expect(screen.queryByText("Undo update")).not.toBeInTheDocument();

    const undoable = engineUpdates({ can_undo: true, busy_chats: 1 });
    api.updates.mockResolvedValue(undoable);
    push(changed(undoable));
    await user.click(screen.getByRole("button", { name: "Undo" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("1 chat is mid-turn");
    expect(api.undoUpdate).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Undo update" }));

    expect(api.undoUpdate).toHaveBeenCalledOnce();
    // The row outlasts `can_undo`, which the daemon clears as soon as it agrees.
    push(changed(engineUpdates()));
    expect(await screen.findByRole("button", { name: "Undoing..." })).toBeDisabled();
  });
});
