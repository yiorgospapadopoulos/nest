import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import { USAGE_BAR_HIDDEN_KEY } from "../../store/devicePrefs.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { claudeProvider, codexProvider, usagePeriod, usageSettings } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { openSettings } from "../../test/settings.ts";

const openUsage = (api = fakeApi()) => openSettings("Usage", { api });

describe("usage page", () => {
  it("shows the limits and the period, with the usage settings under them", async () => {
    await openUsage();

    expect(screen.getByRole("heading", { level: 1, name: "Usage" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/settings/usage");
    await screen.findByLabelText("Check limits");
    const limits = screen.getByRole("meter", { name: "5 hour used" });
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
    const api = fakeApi();
    api.usageSettings.mockReturnValue(new Promise(() => undefined));
    await openUsage(api);

    expect(await screen.findByRole("meter", { name: "5 hour used" })).toBeInTheDocument();
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

describe("usage per engine", () => {
  it("shows Codex's windows under Claude's, and refreshes both", async () => {
    const api = withCodex();
    const { user } = await openUsage(api);

    const limits = await screen.findByRole("region", { name: /^Limits/ });
    expect(await within(limits).findByRole("meter", { name: "Codex 5 hour used" })).toHaveAttribute(
      "aria-valuenow",
      "20",
    );
    expect(within(limits).getByRole("meter", { name: "Codex Weekly used" })).toHaveAttribute(
      "aria-valuenow",
      "45",
    );
    expect(within(limits).getByRole("meter", { name: "5 hour used" })).toBeInTheDocument();
    expect(within(limits).getByText("Claude")).toBeInTheDocument();
    expect(within(limits).getByText("Codex")).toBeInTheDocument();
    expect(api.engineLimits).toHaveBeenCalledWith("codex");

    await user.click(within(limits).getByRole("button", { name: "Refresh usage" }));
    expect(api.refreshUsage).toHaveBeenCalled();
    expect(api.refreshEngineUsage).toHaveBeenCalledWith("codex");
  });

  it("follows Codex's windows live, and waits for a first report", async () => {
    const api = withCodex();
    api.engineLimits.mockRejectedValue(new ApiError(502, "codex is down"));
    const { push } = await openUsage(api);
    const limits = await screen.findByRole("region", { name: /^Limits/ });
    await within(limits).findByText("Codex");
    expect(within(limits).getByText("Usage").nextElementSibling).toHaveTextContent(
      "Not reported yet",
    );

    push({
      type: "usage.provider_updated",
      payload: {
        provider: "codex",
        windows: [{ utilization: 0.6, resets_at: null, minutes: 43200, label: "30 day" }],
      },
    });
    expect(within(limits).getByRole("meter", { name: "Codex 30 day used" })).toHaveAttribute(
      "aria-valuenow",
      "60",
    );
  });

  it("leaves out an engine that is not signed in, and its refresh", async () => {
    const api = withCodex(fakeApi(), false);
    const { user } = await openUsage(api);
    const limits = await screen.findByRole("region", { name: /^Limits/ });
    await waitFor(() => {
      expect(api.providers).toHaveBeenCalled();
    });

    expect(within(limits).queryByText("Codex")).toBeNull();
    expect(within(limits).queryByText("Claude")).toBeNull();
    await user.click(within(limits).getByRole("button", { name: "Refresh usage" }));
    expect(api.refreshEngineUsage).not.toHaveBeenCalled();
  });
});

describe("top bar shows", () => {
  it("checks an engine per row, kept on this device", async () => {
    const storage = memoryStorage();
    const api = withCodex(fakeApi(), false);
    const { user } = await openSettings("Usage", { api, storage });

    const bar = await screen.findByRole("region", { name: "Top bar shows" });
    const codex = await within(bar).findByRole("checkbox", { name: "Show Codex in the top bar" });
    expect(codex).toBeChecked();
    expect(within(bar).getByText("Not signed in")).toBeInTheDocument();
    expect(within(bar).getByRole("checkbox", { name: "Show Claude in the top bar" })).toBeChecked();

    await user.click(codex);
    expect(codex).not.toBeChecked();
    expect(storage.getItem(USAGE_BAR_HIDDEN_KEY)).toBe(JSON.stringify(["codex"]));
    await user.click(codex);
    expect(codex).toBeChecked();
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
