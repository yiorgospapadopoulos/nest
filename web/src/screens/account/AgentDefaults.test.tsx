import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { account, agentDefaults } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

async function openAccount(api = fakeApi()) {
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Account" }));
  return rendered;
}

const section = (name: string) => screen.getByRole("region", { name });

describe("profile", () => {
  it("shows the name and plan, and the email only when asked", async () => {
    const { user } = await openAccount();

    const profile = await screen.findByRole("region", { name: "Profile" });
    expect(await within(profile).findByText("Sam")).toBeInTheDocument();
    expect(within(profile).getByText("Claude Max")).toBeInTheDocument();
    expect(within(profile).queryByText("me@example.com")).not.toBeInTheDocument();

    await user.click(within(profile).getByRole("button", { name: "Show email" }));

    expect(within(profile).getByText("me@example.com")).toBeInTheDocument();
    expect(within(profile).queryByRole("button", { name: "Show email" })).toBeNull();
  });

  it("falls back when the account is unknown", async () => {
    const api = fakeApi();
    api.account.mockResolvedValue(
      account({ display_name: null, email: null, plan: null, organization: null }),
    );
    await openAccount(api);

    const profile = section("Profile");
    expect(await within(profile).findByText("Claude account")).toBeInTheDocument();
    expect(within(profile).getByText("Plan not reported")).toBeInTheDocument();
    expect(within(profile).queryByRole("button", { name: "Show email" })).toBeNull();
  });

  it("waits for the Mac", async () => {
    const api = fakeApi();
    api.account.mockReturnValue(new Promise(() => undefined));
    await openAccount(api);

    expect(within(section("Profile")).getByText("Loading...")).toBeInTheDocument();
  });
});

describe("agent defaults", () => {
  it("shows the current defaults with the engine's models", async () => {
    const api = fakeApi();
    api.agentDefaults.mockResolvedValue(
      agentDefaults({ model: "opus", effort: "xhigh", permission_mode: "plan", mode: "worktree" }),
    );
    await openAccount(api);

    const card = await screen.findByRole("region", { name: "Agent defaults" });
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
    expect(within(card).getByLabelText("Permission mode")).toHaveValue("plan");
    expect(within(card).getByRole("button", { name: "Worktree" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("saves each change, dropping a thinking level the new model does not take", async () => {
    const api = fakeApi();
    api.agentDefaults.mockResolvedValue(agentDefaults({ effort: "xhigh" }));
    const { user } = await openAccount(api);
    const card = await screen.findByRole("region", { name: "Agent defaults" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Thinking")).toHaveValue("xhigh");
    });

    await user.selectOptions(within(card).getByLabelText("Model"), "claude-opus-4-6");
    await user.selectOptions(within(card).getByLabelText("Thinking"), "max");
    await user.selectOptions(within(card).getByLabelText("Permission mode"), "acceptEdits");
    await user.click(within(card).getByRole("button", { name: "Worktree" }));
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
    const card = await screen.findByRole("region", { name: "Agent defaults" });
    const permission = () => within(card).getByLabelText("Permission mode");
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
    const card = await screen.findByRole("region", { name: "Agent defaults" });
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

    const card = await screen.findByRole("region", { name: "Agent defaults" });
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

    const card = await screen.findByRole("region", { name: "Agent defaults" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Model")).toHaveValue("claude-x");
    });
    expect(within(card).getByLabelText("Thinking")).toHaveValue("low");
  });

  it("keeps working without the model list", async () => {
    const api = fakeApi();
    api.models.mockRejectedValue(new Error("offline"));
    await openAccount(api);

    const card = await screen.findByRole("region", { name: "Agent defaults" });
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

    const card = await screen.findByRole("region", { name: "Agent defaults" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Permission mode")).toHaveValue("auto");
    });
    expect(within(card).getByLabelText("Permission mode")).toHaveDisplayValue("Auto");
  });

  it("keeps Auto when another default changes while the model list is unknown", async () => {
    const api = fakeApi();
    api.models.mockRejectedValue(new Error("offline"));
    api.agentDefaults.mockResolvedValue(
      agentDefaults({ permission_mode: "auto", mode: "in_place" }),
    );
    const { user } = await openAccount(api);
    const card = await screen.findByRole("region", { name: "Agent defaults" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Permission mode")).toHaveValue("auto");
    });

    await user.click(within(card).getByRole("button", { name: "Worktree" }));

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
    const card = await screen.findByRole("region", { name: "Agent defaults" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Permission mode")).toHaveValue("default");
    });

    await user.selectOptions(within(card).getByLabelText("Permission mode"), "plan");

    expect(await screen.findByText("Haiku 4.5 does not take a thinking level")).toBeInTheDocument();
    expect(within(card).getByLabelText("Permission mode")).toHaveValue("default");
  });

  it("waits for the Mac", async () => {
    const api = fakeApi();
    api.agentDefaults.mockReturnValue(new Promise(() => undefined));
    await openAccount(api);

    expect(within(section("Agent defaults")).getByText("Loading...")).toBeInTheDocument();
  });
});
