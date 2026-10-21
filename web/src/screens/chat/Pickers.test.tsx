import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ModelList, Session } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { defined } from "../../test/defined.ts";
import {
  agentDefaults,
  claudeProvider,
  codexProvider,
  detail,
  modelList,
  repo,
  session,
} from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

// Codex's models (B91): its own default and no thinking levels of Claude's.
const CODEX: ModelList = {
  models: [
    {
      value: "gpt-5.5-codex",
      display_name: "GPT-5.5 Codex",
      description: "Tuned for coding",
      effort_levels: ["low", "medium", "high"],
      supports_effort: true,
      supports_auto_mode: false,
      claude_code_effort: null,
    },
    {
      value: "gpt-5.5-mini",
      display_name: "GPT-5.5 mini",
      description: "",
      effort_levels: [],
      supports_effort: false,
      supports_auto_mode: false,
      claude_code_effort: null,
    },
  ],
  updated_at: "2026-10-06T10:00:00Z",
  default_model: "gpt-5.5-codex",
};

/** Claude and Codex, Codex signed in unless said otherwise. */
function twoEngines(api: FakeApi, codex = codexProvider()) {
  api.providers.mockResolvedValue({ providers: [claudeProvider(), codex] });
  api.models.mockImplementation((provider) =>
    Promise.resolve(provider === "codex" ? CODEX : modelList({ default_model: "opus" })),
  );
}

async function openChat(chat: Session, api: FakeApi = fakeApi()) {
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.updateSession.mockImplementation((_id, body) => Promise.resolve({ ...chat, ...body }));
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  await waitFor(() => {
    expect(api.models).toHaveBeenCalled();
  });
  return rendered;
}

async function newChat(api: FakeApi = fakeApi()) {
  api.repos.mockResolvedValue([repo("cv-page")]);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: "New chat in cv-page" }));
  await screen.findByRole("button", { name: /^Model: / });
  return rendered;
}

const options = (dialog: HTMLElement) =>
  within(dialog)
    .getAllByRole("menuitemradio")
    .map((item) => item.textContent);

describe("model selector", () => {
  it("lists the engine's real models with descriptions and checks the chat's model", async () => {
    const { user } = await openChat(session({ model: "opus" }));

    await user.click(await screen.findByRole("button", { name: "Model: Opus 5.5" }));
    const sheet = screen.getByRole("dialog", { name: "Model" });

    // No "Default" entry (B94).
    expect(options(sheet)).toEqual([
      "Opus 5.5Most capable for complex work",
      "Haiku 4.5Fastest for quick answers",
      "Opus 4.6Previous Opus",
    ]);
    expect(within(sheet).getByRole("menuitemradio", { name: /^Opus 5.5/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("names a chat stored with an alias by the listed model it stands for", async () => {
    const api = fakeApi();
    const list = modelList();
    api.models.mockResolvedValue({
      ...list,
      models: list.models.map((m) => (m.value === "opus" ? { ...m, value: "claude-opus-5-5" } : m)),
    });
    const { user } = await openChat(session({ model: "opus" }), api);

    await user.click(await screen.findByRole("button", { name: "Model: Opus 5.5" }));

    expect(screen.getByRole("menuitemradio", { name: /^Opus 5.5/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("reads a chat without a model as its engine's default model", async () => {
    const api = fakeApi();
    api.models.mockResolvedValue(modelList({ default_model: "opus" }));
    const { user } = await openChat(session({ model: null }), api);

    await user.click(await screen.findByRole("button", { name: "Model: Opus 5.5" }));

    expect(screen.getByRole("menuitemradio", { name: /^Opus 5.5/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("has nothing to list until the Mac answers", async () => {
    const api = fakeApi();
    api.models.mockRejectedValue(new Error("offline"));
    api.agentDefaults.mockRejectedValue(new Error("offline"));
    const { user } = await openChat(session({ model: "opus" }), api);

    await user.click(screen.getByRole("button", { name: "Model: opus" }));

    expect(screen.queryAllByRole("menuitemradio")).toEqual([]);
    expect(screen.getByRole("menuitem", { name: "Models unavailable" })).toBeDisabled();
    expect(screen.queryByText("offline")).not.toBeInTheDocument();
  });

  it("starts a new chat from the concrete agent defaults, with no Default entry", async () => {
    const api = fakeApi();
    api.agentDefaults.mockResolvedValue(
      agentDefaults({ model: "opus", effort: "high", permission_mode: "acceptEdits" }),
    );
    const { user } = await newChat(api);

    expect(screen.getByRole("button", { name: "Model: Opus 5.5" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thinking: High" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Permission mode: Accept edits" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Model: Opus 5.5" }));
    expect(options(screen.getByRole("dialog", { name: "Model" }))).not.toContainEqual(
      expect.stringMatching(/Default/),
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.type(screen.getByLabelText("Message"), "Go{Enter}");

    expect(api.createSession).toHaveBeenCalledWith({
      repo: "cv-page",
      prompt: "Go",
      attachment_ids: [],
      provider: "claude",
      model: "opus",
      effort: "high",
      permission_mode: "acceptEdits",
      mode: "worktree",
      base: "main",
    });
  });

  it("shows no selectors in a new chat until the agent defaults are known", async () => {
    const api = fakeApi();
    api.agentDefaults.mockRejectedValue(new Error("offline"));
    api.repos.mockResolvedValue([repo("cv-page")]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));
    await waitFor(() => {
      expect(api.agentDefaults).toHaveBeenCalled();
    });

    expect(screen.queryByRole("button", { name: /^Model: / })).not.toBeInTheDocument();
    // `/model` has nothing to set yet.
    await user.type(screen.getByLabelText("Message"), "/model opus{Enter}");
    expect(screen.queryByRole("dialog", { name: "Model" })).not.toBeInTheDocument();
    // The Mac's own defaults apply.
    await user.type(screen.getByLabelText("Message"), "Go{Enter}");
    expect(api.createSession).toHaveBeenCalledWith({
      repo: "cv-page",
      prompt: "Go",
      attachment_ids: [],
      mode: "worktree",
      base: "main",
    });
  });
});

describe("engines in the model menu (B91)", () => {
  it("lists each engine under its name and plan in a new chat; a model picks its engine", async () => {
    const api = fakeApi();
    twoEngines(api);
    const { user } = await newChat(api);

    await user.click(await screen.findByRole("button", { name: "Model: Opus 5.5" }));
    const sheet = screen.getByRole("dialog", { name: "Model" });
    const claude = within(sheet).getByRole("group", { name: "Claude" });
    const codex = within(sheet).getByRole("group", { name: "Codex" });
    expect(claude).toHaveTextContent(/^ClaudeClaude Max/);
    expect(codex).toHaveTextContent(/^CodexChatGPT Plus/);
    expect(options(codex)).toEqual(["GPT-5.5 CodexTuned for coding", "GPT-5.5 mini"]);
    expect(within(codex).getByRole("menuitemradio", { name: /^GPT-5.5 Codex/ })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    await user.click(within(codex).getByRole("menuitemradio", { name: /^GPT-5.5 Codex/ }));

    // Its thinking and modes follow the engine's model: Medium, and no Auto.
    expect(screen.getByRole("button", { name: "Model: GPT-5.5 Codex" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thinking: Medium" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Permission mode: Ask" }));
    expect(options(screen.getByRole("dialog", { name: "Permission mode" }))).not.toContain(
      "AutoClaude decides what needs asking",
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.type(screen.getByLabelText("Message"), "Go{Enter}");

    expect(api.createSession).toHaveBeenCalledWith(
      expect.objectContaining({ provider: "codex", model: "gpt-5.5-codex", effort: "medium" }),
    );
  });

  it("says when the chosen engine is not signed in", async () => {
    const api = fakeApi();
    twoEngines(api, codexProvider({ signed_in: false, sign_in_hint: "Run codex login." }));
    const { user } = await newChat(api);

    await user.click(await screen.findByRole("button", { name: "Model: Opus 5.5" }));
    const codex = within(screen.getByRole("dialog", { name: "Model" })).getByRole("group", {
      name: "Codex",
    });
    expect(codex).toHaveTextContent(/^CodexNot signed in/);
    expect(screen.queryByText("Run codex login.")).not.toBeInTheDocument();
    await user.click(within(codex).getByRole("menuitemradio", { name: /^GPT-5.5 mini/ }));

    expect(screen.getByText("Run codex login.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thinking: No thinking" })).toBeDisabled();
    // A model without thinking sends no level.
    await user.type(screen.getByLabelText("Message"), "Go{Enter}");
    expect(api.createSession.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({ provider: "codex", model: "gpt-5.5-mini" }),
    );
    expect(api.createSession.mock.calls[0]?.[0]).not.toHaveProperty("effort");
  });

  it("sets a new chat's model with /model, by name", async () => {
    const api = fakeApi();
    twoEngines(api);
    const { user } = await newChat(api);

    await user.type(screen.getByLabelText("Message"), "/model haiku 4.5{Enter}");

    expect(await screen.findByRole("button", { name: "Model: Haiku 4.5" })).toBeInTheDocument();
  });

  it("lists only the open chat's own engine", async () => {
    const api = fakeApi();
    twoEngines(api);
    const { user } = await openChat(session({ provider: "codex", model: null }), api);

    await user.click(await screen.findByRole("button", { name: "Model: GPT-5.5 Codex" }));
    const sheet = screen.getByRole("dialog", { name: "Model" });

    expect(within(sheet).queryByRole("group", { name: "Claude" })).not.toBeInTheDocument();
    await user.click(within(sheet).getByRole("menuitemradio", { name: /^GPT-5.5 mini/ }));
    expect(api.updateSession).toHaveBeenCalledWith("s1", { model: "gpt-5.5-mini" });
  });
});

describe("thinking selector", () => {
  it("shows only the levels of the chat's model", async () => {
    const { user } = await openChat(session({ model: "claude-opus-4-6", effort: "high" }));

    await user.click(screen.getByRole("button", { name: "Thinking: High" }));

    expect(options(screen.getByRole("dialog", { name: "Thinking" }))).toEqual([
      "Low",
      "Medium",
      "High",
      "Max",
    ]);
  });

  it("shows every level, Extra high and Max included, for a model the list lacks", async () => {
    const { user } = await openChat(session({ model: "claude-next", effort: null }));

    await user.click(screen.getByRole("button", { name: "Thinking: Thinking" }));

    expect(options(screen.getByRole("dialog", { name: "Thinking" }))).toEqual([
      "Low",
      "Medium",
      "High",
      "Extra high",
      "Max",
    ]);
  });

  it("names a mode this app does not know yet as the Mac sends it", async () => {
    const chat = session({ model: "opus", permission_mode: "dontAsk" as never });
    await openChat(chat);

    expect(screen.getByRole("button", { name: "Permission mode: dontAsk" })).toBeInTheDocument();
  });

  it("is not available for Haiku", async () => {
    await openChat(session({ model: "haiku", effort: null }));

    expect(screen.getByRole("button", { name: "Thinking: No thinking" })).toBeDisabled();
  });

  it("applies a level to an open chat", async () => {
    const { user, api } = await openChat(session({ model: "opus", effort: "low" }));

    await user.click(screen.getByRole("button", { name: "Thinking: Low" }));
    await user.click(screen.getByRole("menuitemradio", { name: "Max" }));

    expect(api.updateSession).toHaveBeenCalledWith("s1", { effort: "max" });
  });

  it("keeps the nearest level a newly chosen model takes", async () => {
    const api = fakeApi();
    api.agentDefaults.mockResolvedValue(agentDefaults({ model: "opus" }));
    const { user } = await newChat(api);
    const pick = async (selector: string, option: RegExp) => {
      await user.click(screen.getByRole("button", { name: selector }));
      await user.click(screen.getByRole("menuitemradio", { name: option }));
    };

    await pick("Thinking: Medium", /Extra high/);
    await pick("Model: Opus 5.5", /^Opus 4.6/);
    expect(screen.getByRole("button", { name: "Thinking: High" })).toBeInTheDocument();
    await pick("Model: Opus 4.6", /^Haiku/);
    expect(screen.getByRole("button", { name: "Thinking: No thinking" })).toBeDisabled();
    await pick("Model: Haiku 4.5", /^Opus 5.5/);
    await user.type(screen.getByLabelText("Message"), "Go{Enter}");

    expect(api.createSession).toHaveBeenCalledWith(
      expect.objectContaining({ model: "opus", effort: "medium" }),
    );
  });
});

describe("permission mode selector", () => {
  it("offers Auto for a model that takes it", async () => {
    const { user, api } = await openChat(session({ model: "opus", permission_mode: "default" }));

    await user.click(screen.getByRole("button", { name: "Permission mode: Ask" }));
    const sheet = screen.getByRole("dialog", { name: "Permission mode" });
    expect(options(sheet)).toEqual([
      "AskAsks before edits and commands",
      "Accept editsEdits files without asking",
      "PlanReads and plans only",
      "BypassRuns everything without asking",
      "AutoClaude decides what needs asking",
    ]);
    await user.click(within(sheet).getByRole("menuitemradio", { name: /^Auto/ }));

    expect(api.updateSession).toHaveBeenCalledWith("s1", { permission_mode: "auto" });
    expect(
      await screen.findByRole("button", { name: "Permission mode: Auto" }),
    ).toBeInTheDocument();
  });

  it("leaves Auto out for a model that does not take it", async () => {
    const { user } = await openChat(session({ model: "haiku" }));

    await user.click(screen.getByRole("button", { name: "Permission mode: Ask" }));

    expect(options(screen.getByRole("dialog", { name: "Permission mode" }))).not.toContain(
      "AutoClaude decides what needs asking",
    );
  });

  it("follows the model a new chat will use", async () => {
    const api = fakeApi();
    api.agentDefaults.mockResolvedValue(agentDefaults({ model: "haiku" }));
    const { user } = await newChat(api);
    const permissions = async () => {
      await user.click(screen.getByRole("button", { name: /^Permission mode:/ }));
      const found = options(screen.getByRole("dialog", { name: "Permission mode" }));
      await user.click(screen.getByRole("button", { name: "Cancel" }));
      return found;
    };

    expect(await permissions()).toHaveLength(4);
    await user.click(screen.getByRole("button", { name: "Model: Haiku 4.5" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Opus 5.5/ }));
    expect(await permissions()).toHaveLength(5);
    await user.click(screen.getByRole("button", { name: "Permission mode: Ask" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Auto/ }));
    await user.click(screen.getByRole("button", { name: "Model: Opus 5.5" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Haiku/ }));
    // Haiku does not take Auto: the new chat goes back to the agent default's mode.
    expect(screen.getByRole("button", { name: "Permission mode: Ask" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Permission mode: Ask" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Plan/ }));
    expect(defined(screen.getByRole("button", { name: "Permission mode: Plan" }))).toBeVisible();
  });
});
