import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { agentDefaults, stuckSettings, usageSettings } from "../../test/fixtures.ts";
import { openSettings } from "../../test/settings.ts";

const openAccount = (api = fakeApi()) => openSettings("Agents", { api });

const section = (name: string) => screen.getByRole("region", { name });

describe("agent defaults", () => {
  it("shows the current defaults with the engine's models", async () => {
    const api = fakeApi();
    api.agentDefaults.mockResolvedValue(
      agentDefaults({ model: "opus", effort: "xhigh", permission_mode: "plan", mode: "worktree" }),
    );
    await openAccount(api);

    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Model")).toHaveValue("opus");
    });
    const model = within(card).getByLabelText("Model");
    expect(
      within(model)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Default (recommended)", "Opus 5.5", "Haiku 4.5", "Opus 4.6"]);
    expect(within(card).getByLabelText("Thinking")).toHaveValue("xhigh");
    const thinking = within(card).getByLabelText("Thinking");
    expect(
      within(thinking)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Model default", "Low", "Medium", "High", "Extra high", "Max"]);
    expect(within(card).getByLabelText("Permissions")).toHaveValue("plan");
    expect(within(card).getByRole("button", { name: "New worktree" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      within(within(card).getByRole("group", { name: "Work in" }))
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Current branch", "New worktree"]);
  });

  it("saves each change, dropping a thinking level the new model does not take", async () => {
    const api = fakeApi();
    api.agentDefaults.mockResolvedValue(agentDefaults({ effort: "xhigh" }));
    const { user } = await openAccount(api);
    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Thinking")).toHaveValue("xhigh");
    });

    await user.selectOptions(within(card).getByLabelText("Model"), "claude-opus-4-6");
    await user.selectOptions(within(card).getByLabelText("Thinking"), "max");
    await user.selectOptions(within(card).getByLabelText("Permissions"), "acceptEdits");
    await user.click(within(card).getByRole("button", { name: "New worktree" }));
    await user.selectOptions(within(card).getByLabelText("Thinking"), "");

    expect(api.saveAgentDefaults.mock.calls.map(([body]) => body)).toEqual([
      agentDefaults({ model: "claude-opus-4-6" }),
      agentDefaults({ model: "claude-opus-4-6", effort: "max" }),
      agentDefaults({ model: "claude-opus-4-6", effort: "max", permission_mode: "acceptEdits" }),
      agentDefaults({
        model: "claude-opus-4-6",
        effort: "max",
        permission_mode: "acceptEdits",
        mode: "worktree",
      }),
      agentDefaults({ model: "claude-opus-4-6", permission_mode: "acceptEdits", mode: "worktree" }),
    ]);
  });

  it("leaves the permission mode to Claude Code, and offers Auto where the model takes it", async () => {
    const api = fakeApi();
    api.agentDefaults.mockResolvedValue(agentDefaults({ permission_mode: null }));
    const { user } = await openAccount(api);
    const card = await screen.findByRole("region", { name: "New chats" });
    const permission = () => within(card).getByLabelText("Permissions");
    await waitFor(() => {
      expect(permission()).toHaveDisplayValue("Claude Code default");
    });
    expect(
      within(permission())
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Claude Code default", "Ask", "Accept edits", "Plan", "Bypass", "Auto"]);

    await user.selectOptions(permission(), "auto");
    await user.selectOptions(within(card).getByLabelText("Model"), "haiku");
    expect(within(permission()).queryByRole("option", { name: "Auto" })).toBeNull();
    await user.selectOptions(permission(), "plan");
    await user.selectOptions(permission(), "");

    expect(api.saveAgentDefaults.mock.calls.map(([body]) => body)).toEqual([
      agentDefaults({ permission_mode: "auto" }),
      // Haiku does not take Auto, so the mode goes back to Claude Code's.
      agentDefaults({ model: "haiku", permission_mode: null }),
      agentDefaults({ model: "haiku", permission_mode: "plan" }),
      agentDefaults({ model: "haiku", permission_mode: null }),
    ]);
  });

  it("names the thinking level Claude Code gives the model by default", async () => {
    const api = fakeApi();
    const { user } = await openAccount(api);
    const card = await screen.findByRole("region", { name: "New chats" });
    const thinking = () => within(card).getByLabelText("Thinking");
    await waitFor(() => {
      expect(thinking()).toHaveDisplayValue("Model default (High, from Claude Code)");
    });

    await user.selectOptions(within(card).getByLabelText("Model"), "opus");
    expect(thinking()).toHaveDisplayValue("Model default");
    await user.selectOptions(within(card).getByLabelText("Model"), "claude-opus-4-6");
    expect(thinking()).toHaveDisplayValue("Model default (Medium, from Claude Code)");
  });

  it("has no thinking for Haiku", async () => {
    const api = fakeApi();
    api.agentDefaults.mockResolvedValue(agentDefaults({ model: "haiku" }));
    await openAccount(api);

    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Thinking")).toBeDisabled();
    });
    expect(within(card).getByLabelText("Thinking")).toHaveDisplayValue(
      "Not available for this model",
    );
  });

  it("keeps a model the list does not know", async () => {
    const api = fakeApi();
    api.agentDefaults.mockResolvedValue(agentDefaults({ model: "claude-x", effort: "low" }));
    await openAccount(api);

    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Model")).toHaveValue("claude-x");
    });
    expect(within(card).getByLabelText("Thinking")).toHaveValue("low");
  });

  it("keeps working without the model list", async () => {
    const api = fakeApi();
    api.models.mockRejectedValue(new Error("offline"));
    await openAccount(api);

    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Model")).toHaveValue("default");
    });
    const model = within(card).getByLabelText("Model");
    expect(
      within(model)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["default"]);
    expect(within(within(card).getByLabelText("Thinking")).getAllByRole("option")).toHaveLength(6);
  });

  it("keeps Auto while the model list is unknown", async () => {
    const api = fakeApi();
    api.models.mockRejectedValue(new Error("offline"));
    api.agentDefaults.mockResolvedValue(agentDefaults({ permission_mode: "auto" }));
    await openAccount(api);

    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Permissions")).toHaveValue("auto");
    });
    expect(within(card).getByLabelText("Permissions")).toHaveDisplayValue("Auto");
  });

  it("keeps Auto when another default changes while the model list is unknown", async () => {
    const api = fakeApi();
    api.models.mockRejectedValue(new Error("offline"));
    api.agentDefaults.mockResolvedValue(
      agentDefaults({ permission_mode: "auto", mode: "in_place" }),
    );
    const { user } = await openAccount(api);
    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Permissions")).toHaveValue("auto");
    });

    await user.click(within(card).getByRole("button", { name: "New worktree" }));

    expect(api.saveAgentDefaults).toHaveBeenCalledWith(
      agentDefaults({ permission_mode: "auto", mode: "worktree" }),
    );
  });

  it("puts the previous defaults back when the Mac refuses", async () => {
    const api = fakeApi();
    api.saveAgentDefaults.mockRejectedValue(
      new ApiError(422, "Haiku 4.5 does not take a thinking level"),
    );
    const { user } = await openAccount(api);
    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Permissions")).toHaveValue("default");
    });

    await user.selectOptions(within(card).getByLabelText("Permissions"), "plan");

    expect(await screen.findByText("Haiku 4.5 does not take a thinking level")).toBeInTheDocument();
    expect(within(card).getByLabelText("Permissions")).toHaveValue("default");
  });

  it("waits for the Mac", async () => {
    const api = fakeApi();
    api.agentDefaults.mockReturnValue(new Promise(() => undefined));
    await openAccount(api);

    expect(within(section("New chats")).getByText("Loading...")).toBeInTheDocument();
  });
});

describe("usage limit settings", () => {
  const options = (label: string) =>
    within(screen.getByLabelText(label))
      .getAllByRole("option")
      .map((o) => o.textContent);

  it("sets how often limits are checked and when to warn", async () => {
    const api = fakeApi();
    const { user } = await openAccount(api);
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
    await openAccount(api);

    expect(await screen.findByLabelText("Check limits")).toHaveDisplayValue("Every 7 minutes");
    expect(screen.getByLabelText("Warn me at")).toHaveDisplayValue("95%");
  });

  it("waits for the settings", async () => {
    const api = fakeApi();
    api.usageSettings.mockReturnValue(new Promise(() => undefined));
    await openAccount(api);

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

describe("stuck chats", () => {
  it("shows the four thresholds and saves a change", async () => {
    const api = fakeApi();
    api.stuckSettings.mockResolvedValue(stuckSettings({ turn_minutes: 150, repeated_calls: 1 }));
    const { user } = await openAccount(api);
    const stuck = await screen.findByRole("region", { name: "Stuck chats" });

    expect(within(stuck).getByLabelText("Waiting for you")).toHaveDisplayValue("15 minutes");
    expect(within(stuck).getByLabelText("No output")).toHaveDisplayValue("10 minutes");
    expect(within(stuck).getByLabelText("Same step repeated")).toHaveDisplayValue(
      "More than 1 times",
    );
    expect(within(stuck).getByLabelText("One turn longer than")).toHaveDisplayValue(
      "2 hours 30 minutes",
    );
    const turn = within(within(stuck).getByLabelText("One turn longer than"))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(turn).toEqual([
      "Off",
      "30 minutes",
      "45 minutes",
      "1 hour",
      "1 hour 30 minutes",
      "2 hours",
      "2 hours 30 minutes",
      "3 hours",
    ]);
    await user.selectOptions(within(stuck).getByLabelText("Waiting for you"), "0");

    expect(api.saveStuckSettings).toHaveBeenCalledWith(
      stuckSettings({ waiting_minutes: 0, turn_minutes: 150, repeated_calls: 1 }),
    );
  });

  it("names a one minute threshold in the singular, and waits for the Mac", async () => {
    const api = fakeApi();
    api.stuckSettings.mockResolvedValue(stuckSettings({ silent_minutes: 1, turn_minutes: 61 }));
    const first = await openAccount(api);
    expect(await screen.findByLabelText("No output")).toHaveDisplayValue("1 minute");
    expect(screen.getByLabelText("One turn longer than")).toHaveDisplayValue("1 hour 1 minute");
    first.unmount();

    api.stuckSettings.mockReturnValue(new Promise(() => undefined));
    await openAccount(api);
    expect(screen.getByRole("region", { name: "Stuck chats" })).toHaveTextContent("Loading...");
  });
});
