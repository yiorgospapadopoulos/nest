import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import { ACCOUNTS_CHANGED } from "../../api/events.ts";
import { USAGE_BAR_HIDDEN_KEY, USAGE_METER_KEY } from "../../store/devicePrefs.ts";
import { accountList, accountWindow, codexAccount, engineAccount } from "../../test/accounts.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { claudeProvider, codexProvider, usagePeriod, usageSettings } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { openSettings } from "../../test/settings.ts";

/** The fake API with Claude's Personal (in use) and Work, and Codex's own login. */
function usageApi(accounts = accountList()) {
  const api = fakeApi();
  api.accounts.mockResolvedValue({ accounts });
  return api;
}

async function openUsage(api = usageApi()) {
  const rendered = await openSettings(null, { api });
  await rendered.user.click(await screen.findByRole("button", { name: "Usage" }));
  return rendered;
}

describe("usage page", () => {
  it("shows the limits and the period, with the usage settings under them", async () => {
    await openUsage();

    expect(screen.getByRole("heading", { level: 1, name: "Usage" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/settings/usage");
    await screen.findByLabelText("Check limits");
    const limits = await screen.findByRole("meter", { name: "Claude · Personal 5 hour used" });
    const period = screen.getByRole("group", { name: "Period" });
    const checks = screen.getByLabelText("Check limits");
    const follows = (before: Node, after: Node) =>
      Boolean(before.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(follows(limits, period)).toBe(true);
    expect(follows(period, checks)).toBe(true);
    expect(screen.getByRole("region", { name: /^Limits/ })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "New chats" })).not.toBeInTheDocument();
  });
});

describe("usage limit settings", () => {
  const options = (label: string) =>
    within(screen.getByLabelText(label))
      .getAllByRole("option")
      .map((o) => o.textContent);

  it("sets how often limits are checked and when to warn", async () => {
    const api = fakeApi();
    const { user } = await openUsage(api);
    await screen.findByLabelText("Check limits");

    expect(options("Check limits")).toEqual([
      "Off",
      "Every minute",
      "Every 3 minutes",
      "Every 5 minutes",
      "Every 10 minutes",
      "Every 15 minutes",
    ]);
    expect(options("Warn me at")).toEqual(["70%", "80%", "90%", "Off"]);
    await user.selectOptions(screen.getByLabelText("Check limits"), "10");
    expect(api.saveUsageSettings).toHaveBeenLastCalledWith(usageSettings({ refresh_minutes: 10 }));
    await user.click(screen.getByRole("switch", { name: "Also as a notification" }));
    expect(api.saveUsageSettings).toHaveBeenLastCalledWith(
      usageSettings({ refresh_minutes: 10, warn_notify: false }),
    );
    await user.selectOptions(screen.getByLabelText("Warn me at"), "null");

    expect(api.saveUsageSettings).toHaveBeenLastCalledWith(
      usageSettings({ refresh_minutes: 10, warn_notify: false, warn_percent: null }),
    );
    expect(screen.getByRole("switch", { name: "Also as a notification" })).toBeDisabled();
    expect(options("Warn me at")).toEqual(["70%", "80%", "90%", "Off"]);
  });

  it("keeps values the lists do not offer", async () => {
    const api = fakeApi();
    api.usageSettings.mockResolvedValue(usageSettings({ refresh_minutes: 7, warn_percent: 95 }));
    await openUsage(api);

    expect(await screen.findByLabelText("Check limits")).toHaveDisplayValue("Every 7 minutes");
    expect(screen.getByLabelText("Warn me at")).toHaveDisplayValue("95%");
  });

  it("waits for the settings", async () => {
    const api = usageApi();
    api.usageSettings.mockReturnValue(new Promise(() => undefined));
    await openUsage(api);

    expect(
      await screen.findByRole("meter", { name: "Claude · Personal 5 hour used" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Check limits")).not.toBeInTheDocument();
  });

  it("shows a usage warning from the Mac as a notice", async () => {
    const { push } = await openSettings(null);

    push({
      type: "usage.warning",
      payload: { window: "five_hour", utilization: 0.823, resets_at: null },
    });
    expect(screen.getByText("5 hour limit 82% used")).toBeInTheDocument();
    push({ type: "usage.warning", payload: { window: "seven_day" } });
    expect(screen.getByText("Weekly limit 0% used")).toBeInTheDocument();
  });
});

/** Codex signed in beside Claude (B94). */
function withCodex(api = fakeApi(), signedIn = true) {
  api.providers.mockResolvedValue({
    providers: [claudeProvider(), codexProvider({ signed_in: signedIn })],
  });
  return api;
}

describe("usage per account (B98)", () => {
  it("shows the account in use of each engine, and refreshes every account", async () => {
    const api = usageApi();
    api.refreshAccounts.mockResolvedValue({ accounts: accountList() });
    const { user } = await openUsage(api);

    const limits = await screen.findByRole("region", { name: /^Limits/ });
    expect(
      await within(limits).findByRole("meter", { name: "Claude · Personal Weekly used" }),
    ).toHaveAttribute("aria-valuenow", "81");
    expect(
      within(limits).getByRole("meter", { name: "Codex · me@example.com 30 day used" }),
    ).toHaveAttribute("aria-valuenow", "4");
    expect(within(limits).getAllByText("in use")).toHaveLength(2);
    expect(within(limits).queryByText(/Claude · Work/)).toBeNull();

    await user.click(within(limits).getByRole("button", { name: "Refresh usage" }));
    expect(api.refreshAccounts).toHaveBeenCalled();
  });

  it("follows accounts.changed, and says a window past its reset reads 0", async () => {
    const { push } = await openUsage();
    const limits = await screen.findByRole("region", { name: /^Limits/ });
    await within(limits).findByText("Claude · Personal");

    push({
      type: ACCOUNTS_CHANGED,
      payload: {
        accounts: [
          engineAccount({ limits: [accountWindow({ utilization: 0.9, reset: true })] }),
          codexAccount({ limits: [] }),
        ],
      } as never,
    });

    const meter = within(limits).getByRole("meter", { name: "Claude · Personal 5 hour used" });
    expect(meter).toHaveAttribute("aria-valuenow", "0");
    expect(within(limits).getByText("Reset")).toBeInTheDocument();
    expect(within(limits).getByText("Not reported yet")).toBeInTheDocument();
  });

  it("says when refreshing again is too soon", async () => {
    const api = usageApi();
    api.refreshAccounts.mockRejectedValue(new ApiError(429, "Too soon"));
    const { user } = await openUsage(api);

    await user.click(await screen.findByRole("button", { name: "Refresh usage" }));

    expect(await screen.findByText("Usage was refreshed moments ago")).toBeInTheDocument();
  });
});

describe("top bar shows (B98)", () => {
  const rows = () =>
    within(screen.getByRole("region", { name: "Top bar shows" }))
      .getAllByRole("checkbox")
      .map((box) => [box.getAttribute("aria-label"), box.getAttribute("aria-checked")]);

  it("lists accounts, checks the account in use of each engine at first, and keeps a change", async () => {
    const storage = memoryStorage();
    const { user } = await openSettings("Usage", { api: usageApi(), storage });

    await within(await screen.findByRole("region", { name: "Top bar shows" })).findByText(
      "Claude · Work",
    );
    expect(rows()).toEqual([
      ["Show Claude · Personal in the top bar", "true"],
      ["Show Claude · Work in the top bar", "false"],
      ["Show Codex · me@example.com in the top bar", "true"],
    ]);
    expect(screen.getByText("Max 20x · in use")).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Show Claude · Work in the top bar" }));

    expect(JSON.parse(storage.getItem(USAGE_METER_KEY) ?? "null")).toEqual({
      order: [],
      shown: ["claude-main", "codex-main", "claude-work"],
    });
    const limits = screen.getByRole("region", { name: /^Limits/ });
    expect(within(limits).getByText("Claude · Work")).toBeInTheDocument();
  });

  it("starts an engine unchecked before (nest.usageBarHidden) unchecked, then drops that key", async () => {
    const storage = memoryStorage();
    storage.setItem(USAGE_BAR_HIDDEN_KEY, JSON.stringify(["codex"]));
    const { user } = await openSettings("Usage", { api: usageApi(), storage });

    await within(await screen.findByRole("region", { name: "Top bar shows" })).findByText(
      "Claude · Work",
    );
    expect(rows()).toEqual([
      ["Show Claude · Personal in the top bar", "true"],
      ["Show Claude · Work in the top bar", "false"],
      ["Show Codex · me@example.com in the top bar", "false"],
    ]);
    const limits = screen.getByRole("region", { name: /^Limits/ });
    expect(within(limits).queryByText(/Codex/)).toBeNull();

    await user.click(screen.getByRole("checkbox", { name: "Show Claude · Work in the top bar" }));
    expect(storage.getItem(USAGE_BAR_HIDDEN_KEY)).toBeNull();
    expect(JSON.parse(storage.getItem(USAGE_METER_KEY) ?? "null")).toEqual({
      order: [],
      shown: ["claude-main", "claude-work"],
    });
  });

  it("moves an account by its handle, kept on this device and read back on the next start", async () => {
    const storage = memoryStorage();
    const first = await openSettings("Usage", { api: usageApi(), storage });

    const grip = await screen.findByRole("button", { name: "Move Codex · me@example.com" });
    grip.focus();
    await first.user.keyboard("{ArrowUp}{ArrowUp}");

    expect(rows().map(([label]) => label)).toEqual([
      "Show Codex · me@example.com in the top bar",
      "Show Claude · Personal in the top bar",
      "Show Claude · Work in the top bar",
    ]);
    expect(JSON.parse(storage.getItem(USAGE_METER_KEY) ?? "null")).toEqual({
      order: ["codex-main", "claude-main", "claude-work"],
      shown: null,
    });
    first.unmount();

    await openSettings("Usage", { api: usageApi(), storage });
    await within(await screen.findByRole("region", { name: "Top bar shows" })).findByText(
      "Claude · Work",
    );
    expect(rows()[0]?.[0]).toBe("Show Codex · me@example.com in the top bar");
    const groups = within(screen.getByRole("region", { name: /^Limits/ }))
      .getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent);
    expect(groups).toEqual(["Codex · me@example.com in use", "Claude · Personal in use"]);
  });

  it("drags an account by its handle", async () => {
    const storage = memoryStorage();
    await openSettings("Usage", { api: usageApi(), storage });

    const grip = await screen.findByRole("button", { name: "Move Claude · Personal" });
    // jsdom has no pointer capture.
    grip.setPointerCapture = () => undefined;
    fireEvent.pointerDown(grip, { pointerId: 1, clientY: 100 });
    fireEvent.pointerMove(grip, { pointerId: 1, clientY: 190 });
    fireEvent.pointerUp(grip, { pointerId: 1, clientY: 190 });

    expect(rows().map(([label]) => label)).toEqual([
      "Show Claude · Work in the top bar",
      "Show Codex · me@example.com in the top bar",
      "Show Claude · Personal in the top bar",
    ]);
  });
});

describe("usage details by engine", () => {
  it("splits the period's tokens by engine", async () => {
    const api = withCodex();
    api.usagePeriod.mockResolvedValue(
      usagePeriod({
        engines: [
          { provider: "claude", tokens: 750, sessions: 3 },
          { provider: "codex", tokens: 250, sessions: 1 },
        ],
      }),
    );
    const { user } = await openUsage(api);
    await user.click(await screen.findByRole("button", { name: "Details" }));

    const engines = await screen.findByRole("region", { name: "By engine" });
    await within(engines).findByText("Codex");
    expect(within(engines).getByText("Claude")).toBeInTheDocument();
    expect(within(engines).getByText("75%")).toBeInTheDocument();
    expect(within(engines).getByText("25%")).toBeInTheDocument();
  });

  it("leaves the split out for a period without engines", async () => {
    const { user } = await openUsage();
    await user.click(await screen.findByRole("button", { name: "Details" }));

    await screen.findByRole("region", { name: "By who" });
    expect(screen.queryByRole("region", { name: "By engine" })).toBeNull();
  });
});

describe("I-B111-1: opened from its address", () => {
  it("shows Codex's limits after a reload", async () => {
    const api = withCodex();
    api.accounts.mockResolvedValue({ accounts: accountList() });
    await openSettings("Usage", { api });

    const limits = await screen.findByRole("region", { name: /^Limits/ });
    expect(
      await within(limits).findByRole("meter", { name: /^Codex.* used$/ }),
    ).toBeInTheDocument();
  });
});
