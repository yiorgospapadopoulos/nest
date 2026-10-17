import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./api/client.ts";
import { App } from "./App.tsx";
import { fakeSubscription, installBrowserPush, uninstallBrowserPush } from "./test/fakePush.ts";
import { socketFactory } from "./test/fakeSocket.ts";
import { fakeApi } from "./test/fakeApi.ts";
import { approval, repo } from "./test/fixtures.ts";
import { renderApp } from "./test/render.tsx";

function unpaired() {
  const api = fakeApi();
  api.repos.mockRejectedValueOnce(new ApiError(401, "not authenticated"));
  return api;
}

describe("App", () => {
  it("loads, opens the event socket and shows the inbox", async () => {
    const { sockets } = await renderApp();

    expect(screen.getByRole("heading", { level: 1, name: "Inbox" })).toBeInTheDocument();
    expect(screen.getByText("All clear")).toBeInTheDocument();
    expect(sockets.last().url).toBe("wss://mac.ts.net/api/events");
  });

  it("tells the daemon while it is on screen, and not before it is paired", async () => {
    const api = unpaired();
    const { unmount } = await renderApp({ api, ready: false });
    await screen.findByRole("heading", { name: "Pair this iPhone" });
    expect(api.reportVisibility).not.toHaveBeenCalled();
    unmount();

    const paired = await renderApp();
    expect(paired.api.reportVisibility).toHaveBeenCalledWith(true);
    paired.unmount();
    expect(paired.api.reportVisibility).toHaveBeenLastCalledWith(false);
  });

  it("shows a loading state until the first snapshot arrives", async () => {
    const api = fakeApi();
    let finish: (value: never[]) => void = () => undefined;
    api.approvals.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    await renderApp({ api, ready: false });

    expect(screen.getByLabelText("Loading")).toHaveAttribute("aria-busy", "true");
    act(() => {
      finish([]);
    });
    expect(await screen.findByText("All clear")).toBeInTheDocument();
  });

  it("asks to pair when the device is not paired, then loads", async () => {
    const api = unpaired();
    const { user } = await renderApp({ api, ready: false });
    const code = await screen.findByLabelText("Pairing code");
    const pair = screen.getByRole("button", { name: "Pair" });
    expect(pair).toBeDisabled();

    await user.type(code, "ab0c-d1e2f3go");
    expect(code).toHaveValue("ABCDE2F3");
    await user.clear(screen.getByLabelText("Device name"));
    expect(pair).toBeDisabled();
    await user.type(screen.getByLabelText("Device name"), " Phone ");
    await user.click(pair);

    expect(await screen.findByText("All clear")).toBeInTheDocument();
    expect(api.redeem).toHaveBeenCalledWith("ABCDE2F3", "Phone");
  });

  it("sends this device's push subscription again on launch and after pairing", async () => {
    installBrowserPush({ permission: "granted", subscription: fakeSubscription() });
    try {
      const launched = await renderApp();
      await waitFor(() => {
        expect(launched.api.subscribePush).toHaveBeenCalledTimes(1);
      });
      launched.unmount();

      const api = unpaired();
      const { user } = await renderApp({ api, ready: false });
      await user.type(await screen.findByLabelText("Pairing code"), "ABCDE2F3");
      await user.click(screen.getByRole("button", { name: "Pair" }));
      await screen.findByText("All clear");

      await waitFor(() => {
        expect(api.subscribePush).toHaveBeenCalledWith({
          endpoint: "https://push/1",
          keys: { p256dh: "p", auth: "a" },
        });
      });
    } finally {
      uninstallBrowserPush();
    }
  });

  it("stays quiet when sending the push subscription again fails", async () => {
    installBrowserPush({ permission: "granted", subscription: fakeSubscription() });
    try {
      const api = fakeApi();
      api.subscribePush.mockRejectedValueOnce(new ApiError(500, "daemon broke"));
      await renderApp({ api });

      await waitFor(() => {
        expect(api.subscribePush).toHaveBeenCalled();
      });
      expect(screen.queryByText("daemon broke")).not.toBeInTheDocument();
    } finally {
      uninstallBrowserPush();
    }
  });

  it("uses the page's own location and storage by default", async () => {
    const sockets = socketFactory();
    render(<App api={fakeApi()} connect={sockets.connect} />);

    expect(await screen.findByText("All clear")).toBeInTheDocument();
    // The socket opens in an effect after the screen that shows the inbox, which can run
    // after the text is found.
    await waitFor(() => {
      expect(sockets.sockets).toHaveLength(1);
    });
    expect(sockets.last().url).toBe(`ws://${window.location.host}/api/events`);
  });

  it("pairs again when an action finds the device revoked", async () => {
    const api = fakeApi();
    api.approvals.mockResolvedValue([approval()]);
    api.resolveApproval.mockRejectedValueOnce(new ApiError(401, "not authenticated"));
    const { user } = await renderApp({ api });

    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByLabelText("Pairing code")).toBeInTheDocument();
  });

  it("toasts failures that are not errors", async () => {
    const api = fakeApi();
    api.approvals.mockResolvedValue([approval()]);
    api.resolveApproval.mockRejectedValueOnce("boom");
    const { user } = await renderApp({ api });

    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
  });

  it.each([
    [new ApiError(500, "broken"), "Could not reach your Mac."],
    [new ApiError(400, "invalid"), "That code is wrong or has expired."],
    [new ApiError(429, "locked"), "Too many attempts. Wait a minute and try again."],
    [new TypeError("offline"), "Could not reach your Mac."],
  ])("explains a failed pairing", async (error, message) => {
    const api = unpaired();
    api.redeem.mockRejectedValueOnce(error);
    const { user } = await renderApp({ api, ready: false });

    await user.type(await screen.findByLabelText("Pairing code"), "ABCDEFGH");
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("button", { name: "Pair" })).toBeEnabled();
  });

  it("does not submit an incomplete code", async () => {
    const api = unpaired();
    const { user } = await renderApp({ api, ready: false });

    await user.type(await screen.findByLabelText("Pairing code"), "ABC{Enter}");

    expect(api.redeem).not.toHaveBeenCalled();
  });

  it("offers a retry when the Mac cannot be reached", async () => {
    const api = fakeApi();
    api.repos.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const { user } = await renderApp({ api, ready: false });

    await user.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByText("All clear")).toBeInTheDocument();
  });

  it("goes back to pairing when the socket rejects the device", async () => {
    const { sockets } = await renderApp();

    act(() => {
      sockets.last().drop(4401);
    });

    expect(await screen.findByLabelText("Pairing code")).toBeInTheDocument();
    expect(sockets.sockets).toHaveLength(1);
  });

  it("explains a rejected origin", async () => {
    const { sockets } = await renderApp();

    act(() => {
      sockets.last().drop(4403);
    });

    expect(await screen.findByText("This address is not allowed")).toBeInTheDocument();
  });

  it("reloads snapshots when the socket opens without a cursor, not when it resumes", async () => {
    const { api, sockets, push } = await renderApp();
    expect(api.repos).toHaveBeenCalledTimes(1);

    act(() => {
      sockets.last().open();
    });
    await waitFor(() => {
      expect(api.repos).toHaveBeenCalledTimes(2);
    });

    push({ id: 3, type: "daemon.started" });
    act(() => {
      sockets.last().drop(1006);
    });
    await waitFor(
      () => {
        expect(sockets.sockets).toHaveLength(2);
      },
      { timeout: 2000 },
    );
    act(() => {
      sockets.last().open();
    });
    expect(sockets.last().url).toBe("wss://mac.ts.net/api/events?after=3");
    expect(api.repos).toHaveBeenCalledTimes(2);
    // The Claude Code chat list changes without stored events, so it reloads on every open.
    await waitFor(() => {
      expect(api.claudeChats).toHaveBeenCalledTimes(3);
    });
  });

  it("says it is reconnecting, and reconnects at once on waking or going online", async () => {
    const { sockets } = await renderApp();
    act(() => {
      sockets.last().open();
    });
    expect(screen.queryByText("Reconnecting...")).not.toBeInTheDocument();
    const regions = screen.queryAllByRole("status");

    act(() => {
      sockets.last().drop(1006);
    });
    // Said in a status region that was already there, so VoiceOver reads it out.
    expect(regions).toContain(screen.getByText("Reconnecting...").closest('[role="status"]'));
    // The phone comes back to the app: no wait for the back-off.
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(sockets.sockets).toHaveLength(2);
    act(() => {
      sockets.last().drop(1006);
      window.dispatchEvent(new Event("online"));
    });
    expect(sockets.sockets).toHaveLength(3);
    act(() => {
      sockets.last().open();
    });

    expect(screen.queryByText("Reconnecting...")).not.toBeInTheDocument();
  });

  it("does not reconnect early while hidden", async () => {
    const { sockets } = await renderApp();
    act(() => {
      sockets.last().drop(1006);
    });
    const hidden = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    try {
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      expect(sockets.sockets).toHaveLength(1);
    } finally {
      hidden.mockRestore();
    }
  });

  it("toasts when a refresh fails and pairs again on 401", async () => {
    const api = fakeApi();
    const { sockets } = await renderApp({ api });
    api.repos.mockRejectedValueOnce(new TypeError("down"));

    act(() => {
      sockets.last().open();
    });
    expect(await screen.findByText("Could not refresh from your Mac")).toBeInTheDocument();

    api.repos.mockRejectedValueOnce(new ApiError(401, "gone"));
    act(() => {
      sockets.last().open();
    });
    expect(await screen.findByLabelText("Pairing code")).toBeInTheDocument();
  });

  it("shows live approvals with a badge on the Inbox tab", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("cv-page")]);
    const { push } = await renderApp({ api });

    push({ id: 1, type: "approval.created", payload: { approval: { ...approval() } } });

    expect(await screen.findByText("npm install zod")).toBeInTheDocument();
    expect(screen.getByLabelText("1 need you")).toBeInTheDocument();
  });

  it("switches tabs with the arrow keys", async () => {
    const { user } = await renderApp();

    screen.getByRole("tab", { name: "Inbox" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Projects" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Projects" })).toHaveFocus();
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "Settings" })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Enter}");
    expect(screen.getByRole("tab", { name: "Settings" })).toHaveAttribute("aria-selected", "true");
  });
});
