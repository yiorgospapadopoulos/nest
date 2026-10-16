import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { fakeSubscription, installBrowserPush, uninstallBrowserPush } from "../../test/fakePush.ts";
import { notificationSettings } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

afterEach(() => {
  uninstallBrowserPush();
});

async function openAccount(api: FakeApi = fakeApi()) {
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Account" }));
  return rendered;
}

const device = () => defined(screen.getByText("This device").parentElement);

describe("this device", () => {
  it("asks to add the app to the Home Screen in a browser tab", async () => {
    installBrowserPush({ standalone: false, push: false });
    await openAccount();

    expect(await screen.findByText(/Add Nest to your Home Screen first/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Enable notifications" })).not.toBeInTheDocument();
  });

  it("explains when push is missing or blocked", async () => {
    installBrowserPush({ push: false });
    const first = await openAccount();
    expect(await screen.findByText(/cannot show notifications/)).toBeInTheDocument();
    first.unmount();

    installBrowserPush({ permission: "denied" });
    await openAccount();
    expect(await screen.findByText(/Notifications are blocked/)).toBeInTheDocument();
  });

  it("enables, tests and turns off notifications", async () => {
    const browser = installBrowserPush();
    const api = fakeApi();
    const { user } = await openAccount(api);

    await user.click(await screen.findByRole("button", { name: "Enable notifications" }));

    expect(browser.requestPermission).toHaveBeenCalled();
    expect(api.subscribePush).toHaveBeenCalledWith({
      endpoint: "https://push/new",
      keys: { p256dh: "p", auth: "a" },
    });
    expect(await screen.findByText("Notifications are on")).toBeInTheDocument();
    expect(device()).toHaveTextContent("On");

    await user.click(screen.getByRole("button", { name: "Send test" }));
    expect(await screen.findByText("Test notification sent")).toBeInTheDocument();
    expect(api.testPush).toHaveBeenCalled();

    api.testPush.mockResolvedValueOnce({ sent: 0, failed: 1, removed: 0 });
    await user.click(screen.getByRole("button", { name: "Send test" }));
    expect(await screen.findByText(/could not be delivered/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Turn off" }));
    expect(api.unsubscribePush).toHaveBeenCalledWith("https://push/new");
    expect(await screen.findByRole("button", { name: "Enable notifications" })).toBeEnabled();
  });

  it("toasts when turning off or testing fails", async () => {
    installBrowserPush({ permission: "granted", subscription: fakeSubscription() });
    const api = fakeApi();
    api.testPush.mockRejectedValueOnce(new ApiError(409, "no subscription here"));
    api.unsubscribePush.mockRejectedValueOnce(new ApiError(500, "cannot forget"));
    const { user } = await openAccount(api);

    await user.click(await screen.findByRole("button", { name: "Send test" }));
    expect(await screen.findByText("no subscription here")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Turn off" }));
    expect(await screen.findByText("cannot forget")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn off" })).toBeEnabled();
  });

  it("shows an existing subscription as on", async () => {
    installBrowserPush({ permission: "granted", subscription: fakeSubscription() });
    await openAccount();

    expect(await screen.findByRole("button", { name: "Turn off" })).toBeInTheDocument();
  });

  it("keeps the button when enabling fails or is declined", async () => {
    installBrowserPush();
    const api = fakeApi();
    api.subscribePush.mockRejectedValueOnce(new ApiError(500, "daemon broke"));
    const { user } = await openAccount(api);

    await user.click(await screen.findByRole("button", { name: "Enable notifications" }));

    expect(await screen.findByText("daemon broke")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enable notifications" })).toBeEnabled();
  });

  it("shows the blocked hint when the prompt is declined", async () => {
    installBrowserPush({ answer: "denied" });
    const { user } = await openAccount();

    await user.click(await screen.findByRole("button", { name: "Enable notifications" }));

    expect(await screen.findByText(/Notifications are blocked/)).toBeInTheDocument();
  });

  it("ignores a status that arrives after leaving the tab", async () => {
    let finish: (value: undefined) => void = () => undefined;
    const browser = installBrowserPush({ permission: "granted" });
    browser.worker.getRegistration = () =>
      new Promise((resolve) => {
        finish = resolve;
      });
    const { user } = await openAccount();
    expect(screen.getByText("Checking...")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Inbox" }));
    await act(async () => {
      finish(undefined);
      await Promise.resolve();
    });

    expect(screen.queryByText("This device")).not.toBeInTheDocument();
  });
});

describe("notification rules", () => {
  const toggle = (name: string) => screen.getByRole("switch", { name });

  it("shows each kind and saves a change", async () => {
    installBrowserPush();
    const api = fakeApi();
    const { user } = await openAccount(api);

    expect(await screen.findByRole("switch", { name: "Approvals" })).toBeChecked();
    expect(toggle("Finished turns")).not.toBeChecked();
    // Pull request checks reach the phone only when switched on (D034).
    expect(toggle("Pull request checks failed")).not.toBeChecked();
    expect(toggle("Pull requests ready to merge")).not.toBeChecked();
    // So do stuck chats (D036); the inbox shows them regardless.
    expect(toggle("Chats that look stuck")).not.toBeChecked();
    // A chat paused at a usage limit says so, on by default (B78).
    expect(toggle("Usage limit pauses")).toBeChecked();
    await user.click(toggle("Finished turns"));

    expect(toggle("Finished turns")).toBeChecked();
    expect(api.saveNotificationSettings).toHaveBeenCalledWith(
      notificationSettings({
        kinds: {
          needs_approval: true,
          question: true,
          review_ready: true,
          failed: true,
          finished: true,
          ci_failed: false,
          ready_to_merge: false,
          stuck: false,
          pixie_report: true,
          usage_limit: true,
        },
      }),
    );
  });

  it("switches pixie reports off (B42)", async () => {
    installBrowserPush();
    const api = fakeApi();
    const { user } = await openAccount(api);

    await user.click(await screen.findByRole("switch", { name: "Pixie reports" }));
    expect(toggle("Pixie reports")).not.toBeChecked();
    expect(api.saveNotificationSettings).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kinds: expect.objectContaining({ pixie_report: false }) as unknown,
      }),
    );
  });

  it("puts a refused change back", async () => {
    installBrowserPush();
    const api = fakeApi();
    api.saveNotificationSettings.mockRejectedValueOnce(new ApiError(409, "settings.toml broke"));
    const { user } = await openAccount(api);

    await user.click(await screen.findByRole("switch", { name: "Questions" }));

    expect(await screen.findByText("settings.toml broke")).toBeInTheDocument();
    expect(toggle("Questions")).toBeChecked();
  });

  it("sets quiet hours and ignores empty or zero-length windows", async () => {
    installBrowserPush();
    const api = fakeApi();
    const { user } = await openAccount(api);

    await user.click(await screen.findByRole("switch", { name: "Quiet hours" }));
    const from = screen.getByLabelText("From");
    const until = screen.getByLabelText("Until");
    expect(from).toHaveValue("22:00");
    expect(until).toHaveValue("07:00");

    fireEvent.change(from, { target: { value: "23:15" } });
    await waitFor(() => {
      expect(api.saveNotificationSettings).toHaveBeenLastCalledWith(
        notificationSettings({ quiet_hours: { start: "23:15", end: "07:00" } }),
      );
    });
    const saves = api.saveNotificationSettings.mock.calls.length;
    fireEvent.change(until, { target: { value: "23:15" } });
    fireEvent.change(until, { target: { value: "" } });
    expect(api.saveNotificationSettings).toHaveBeenCalledTimes(saves);
    fireEvent.change(until, { target: { value: "06:00" } });
    await waitFor(() => {
      expect(screen.getByLabelText("Until")).toHaveValue("06:00");
    });

    await user.click(toggle("Quiet hours"));
    expect(screen.queryByLabelText("From")).not.toBeInTheDocument();
    expect(api.saveNotificationSettings).toHaveBeenLastCalledWith(notificationSettings());
  });

  it("waits for the rules and toasts when they cannot load", async () => {
    installBrowserPush();
    const api = fakeApi();
    api.notificationSettings.mockRejectedValue(new ApiError(500, "no rules"));
    await openAccount(api);

    expect(await screen.findByText("no rules")).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Approvals" })).not.toBeInTheDocument();
  });
});
