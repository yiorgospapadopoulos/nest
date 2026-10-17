import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fakeApi } from "../../test/fakeApi.ts";
import { usageSettings } from "../../test/fixtures.ts";
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
