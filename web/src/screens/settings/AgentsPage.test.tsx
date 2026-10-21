import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { PermissionMode } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import {
  agentDefaults,
  claudeProvider,
  codexProvider,
  modelList,
  stuckSettings,
} from "../../test/fixtures.ts";
import { openSettings } from "../../test/settings.ts";

const openAccount = (api = fakeApi()) => openSettings("Agents", { api });

const section = (name: string) => screen.getByRole("region", { name });

// Codex's list, as the daemon serves it (B94): its own default model named.
const codexModels = modelList({
  default_model: "gpt-5.5",
  models: [
    {
      value: "gpt-5.5",
      display_name: "GPT-5.5",
      description: "Codex's best",
      effort_levels: ["low", "medium", "high"],
      supports_effort: true,
      supports_auto_mode: false,
      claude_code_effort: null,
    },
    {
      value: "gpt-5.5-mini",
      display_name: "GPT-5.5 mini",
      description: "Faster",
      effort_levels: [],
      supports_effort: false,
      supports_auto_mode: false,
      claude_code_effort: null,
    },
  ],
});

/** Claude's list names Opus 5.5 its default; with `codex`, Codex is signed in too. */
function withEngines(codex = false, api = fakeApi()) {
  api.models.mockImplementation((provider) =>
    Promise.resolve(provider === "codex" ? codexModels : modelList({ default_model: "opus" })),
  );
  if (codex) api.providers.mockResolvedValue({ providers: [claudeProvider(), codexProvider()] });
  return api;
}

const options = (select: HTMLElement) =>
  within(select)
    .getAllByRole("option")
    .map((o) => o.textContent);

describe("agent defaults", () => {
  it("shows the concrete defaults, with no default entries", async () => {
    const api = withEngines();
    api.agentDefaults.mockResolvedValue(
      agentDefaults({ model: "opus", effort: "xhigh", permission_mode: "plan", mode: "worktree" }),
    );
    await openAccount(api);

    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Model")).toHaveDisplayValue("Opus 5.5");
    });
    const model = within(card).getByLabelText("Model");
    // One engine: no sections.
    expect(within(model).queryByRole("group")).toBeNull();
    expect(options(model)).toEqual(["Opus 5.5", "Haiku 4.5", "Opus 4.6"]);
    expect(within(card).getByLabelText("Thinking")).toHaveValue("xhigh");
    expect(options(within(card).getByLabelText("Thinking"))).toEqual([
      "Low",
      "Medium",
      "High",
      "Extra high",
      "Max",
    ]);
    expect(within(card).getByLabelText("Permissions")).toHaveValue("plan");
    expect(options(within(card).getByLabelText("Permissions"))).toEqual([
      "Ask",
      "Accept edits",
      "Plan",
      "Bypass",
      "Auto",
    ]);
    expect(within(card).getByRole("button", { name: "New worktree" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      within(within(card).getByRole("group", { name: "Work in" }))
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Current branch", "New worktree"]);
    expect(card).not.toHaveTextContent(/default/i);
  });

  it("reads a default without a model, thinking or mode as what new chats get", async () => {
    const api = withEngines();
    api.agentDefaults.mockResolvedValue(agentDefaults({ permission_mode: null }));
    await openAccount(api);

    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Model")).toHaveDisplayValue("Opus 5.5");
    });
    expect(within(card).getByLabelText("Thinking")).toHaveDisplayValue("Medium");
    expect(within(card).getByLabelText("Permissions")).toHaveDisplayValue("Ask");
  });

  it("offers a section per engine; a model sets the engine, thinking and mode follow it", async () => {
    const api = withEngines(true);
    api.agentDefaults.mockResolvedValue(
      agentDefaults({ model: "opus", effort: "max", permission_mode: "auto" }),
    );
    const { user } = await openAccount(api);
    const card = await screen.findByRole("region", { name: "New chats" });
    const model = () => within(card).getByLabelText("Model");
    await waitFor(() => {
      expect(within(model()).getAllByRole("group")).toHaveLength(2);
    });
    expect(
      within(model())
        .getAllByRole("group")
        .map((g) => g.getAttribute("label")),
    ).toEqual(["Claude · Claude Max", "Codex · ChatGPT Plus"]);
    expect(options(defined(within(model()).getAllByRole("group")[1]))).toEqual([
      "GPT-5.5",
      "GPT-5.5 mini",
    ]);

    await user.selectOptions(model(), "codex gpt-5.5");
    expect(model()).toHaveDisplayValue("GPT-5.5");
    // Max falls to High, the highest GPT-5.5 takes; Auto to Ask.
    expect(within(card).getByLabelText("Thinking")).toHaveValue("high");
    expect(options(within(card).getByLabelText("Permissions"))).not.toContain("Auto");
    await user.selectOptions(model(), "codex gpt-5.5-mini");
    expect(within(card).getByLabelText("Thinking")).toBeDisabled();
    expect(within(card).getByLabelText("Thinking")).toHaveDisplayValue("Not available");
    await user.selectOptions(model(), "claude haiku");

    expect(api.saveAgentDefaults.mock.calls.map(([body]) => body)).toEqual([
      agentDefaults({
        provider: "codex",
        model: "gpt-5.5",
        effort: "high",
        permission_mode: "default",
      }),
      agentDefaults({
        provider: "codex",
        model: "gpt-5.5-mini",
        effort: null,
        permission_mode: "default",
      }),
      agentDefaults({
        provider: "claude",
        model: "haiku",
        effort: null,
        permission_mode: "default",
      }),
    ]);
  });

  it("names a signed out engine in its section", async () => {
    const api = withEngines();
    api.providers.mockResolvedValue({
      providers: [claudeProvider({ account: null }), codexProvider({ signed_in: false })],
    });
    await openAccount(api);
    const card = await screen.findByRole("region", { name: "New chats" });

    await waitFor(() => {
      expect(
        within(within(card).getByLabelText("Model"))
          .getAllByRole("group")
          .map((g) => g.getAttribute("label")),
      ).toEqual(["Claude", "Codex · Not signed in"]);
    });
  });

  it("saves thinking, mode and where chats work", async () => {
    const api = withEngines();
    api.agentDefaults.mockResolvedValue(agentDefaults({ model: "opus" }));
    const { user } = await openAccount(api);
    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Model")).toHaveDisplayValue("Opus 5.5");
    });

    await user.selectOptions(within(card).getByLabelText("Thinking"), "max");
    await user.selectOptions(within(card).getByLabelText("Permissions"), "acceptEdits");
    await user.click(within(card).getByRole("button", { name: "New worktree" }));

    expect(api.saveAgentDefaults.mock.calls.map(([body]) => body)).toEqual([
      agentDefaults({ model: "opus", effort: "max" }),
      agentDefaults({ model: "opus", effort: "max", permission_mode: "acceptEdits" }),
      agentDefaults({
        model: "opus",
        effort: "max",
        permission_mode: "acceptEdits",
        mode: "worktree",
      }),
    ]);
  });

  it("keeps a model, a level and a mode the list does not offer", async () => {
    const api = withEngines();
    api.agentDefaults.mockResolvedValue(
      agentDefaults({ model: "claude-x", effort: "low", permission_mode: "auto" }),
    );
    await openAccount(api);

    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Model")).toHaveDisplayValue("claude-x");
    });
    expect(within(card).getByLabelText("Thinking")).toHaveValue("low");
    // The list does not say claude-x takes Auto; the saved mode still shows.
    expect(within(card).getByLabelText("Permissions")).toHaveDisplayValue("Auto");
  });

  it("shows a mode this app does not know as it is", async () => {
    const api = withEngines();
    api.agentDefaults.mockResolvedValue(
      agentDefaults({ model: "opus", permission_mode: "dontAsk" as PermissionMode }),
    );
    await openAccount(api);

    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Permissions")).toHaveDisplayValue("dontAsk");
    });
  });

  it("keeps a thinking level the model does not list", async () => {
    const api = withEngines();
    api.agentDefaults.mockResolvedValue(
      agentDefaults({ model: "claude-opus-4-6", effort: "xhigh" }),
    );
    await openAccount(api);

    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Thinking")).toHaveDisplayValue("Extra high");
    });
  });

  it("keeps working without the model list", async () => {
    const api = fakeApi();
    api.models.mockRejectedValue(new Error("offline"));
    const { user } = await openAccount(api);

    const card = await screen.findByRole("region", { name: "New chats" });
    await waitFor(() => {
      expect(within(card).getByLabelText("Model")).toHaveDisplayValue("Model");
    });
    expect(options(within(card).getByLabelText("Thinking"))).toHaveLength(5);
    await user.click(within(card).getByRole("button", { name: "New worktree" }));
    expect(api.saveAgentDefaults).toHaveBeenCalledWith(agentDefaults({ mode: "worktree" }));
  });

  it("puts the previous defaults back when the Mac refuses", async () => {
    const api = withEngines();
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

describe("agents page", () => {
  it("holds new chats and stuck chats, and leaves usage to its own page", async () => {
    await openAccount();

    expect(await screen.findByRole("region", { name: "New chats" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Stuck chats" })).toBeInTheDocument();
    expect(screen.queryByRole("meter", { name: "5 hour used" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Check limits")).not.toBeInTheDocument();
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
