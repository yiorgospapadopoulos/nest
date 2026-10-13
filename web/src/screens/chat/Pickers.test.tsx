import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Session } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { defined } from "../../test/defined.ts";
import { agentDefaults, detail, modelList, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

async function openChat(chat: Session, api: FakeApi = fakeApi()) {
  api.repos.mockResolvedValue([repo("todo-ui")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.updateSession.mockImplementation((_id, body) => Promise.resolve({ ...chat, ...body }));
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  await waitFor(() => {
    expect(api.models).toHaveBeenCalled();
  });
  return rendered;
}

async function newChat(api: FakeApi = fakeApi()) {
  api.repos.mockResolvedValue([repo("todo-ui")]);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  await rendered.user.click(screen.getByRole("button", { name: "New chat in todo-ui" }));
  await waitFor(() => {
    expect(api.agentDefaults).toHaveBeenCalled();
  });
  return rendered;
}

const options = (dialog: HTMLElement) =>
  within(dialog)
    .getAllByRole("menuitemradio")
    .map((item) => item.textContent);

describe("model selector", () => {
  it("lists Claude Code's models with descriptions and checks the chat's model", async () => {
    const { user } = await openChat(session({ model: "opus" }));

    await user.click(await screen.findByRole("button", { name: "Model: Opus 5.5" }));
    const sheet = screen.getByRole("dialog", { name: "Model" });

    expect(options(sheet)).toEqual([
      "Default (recommended)Opus 5.5 · Best for everyday, complex tasks",
      "Opus 5.5Most capable for complex work",
      "Haiku 4.5Fastest for quick answers",
      "Opus 4.6Previous Opus",
    ]);
    expect(within(sheet).getByRole("menuitemradio", { name: /^Opus 5.5/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("checks Claude Code's default for a chat without a model", async () => {
    const { user } = await openChat(session({ model: null }));

    await user.click(screen.getByRole("button", { name: "Model: Model" }));

    expect(screen.getByRole("menuitemradio", { name: /^Default \(recommended\)/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("offers the agent default first in a new chat", async () => {
    const { user } = await newChat();

    await user.click(screen.getByRole("button", { name: "Model: Model" }));

    const first = screen.getAllByRole("menuitemradio")[0];
    expect(first).toHaveTextContent("DefaultYour agent default, set in Account");
    expect(first).toHaveAttribute("aria-checked", "true");
  });

  it("has nothing to list until the Mac answers", async () => {
    const api = fakeApi();
    api.models.mockRejectedValue(new Error("offline"));
    api.agentDefaults.mockRejectedValue(new Error("offline"));
    const { user } = await openChat(session({ model: "opus" }), api);

    await user.click(screen.getByRole("button", { name: "Model: opus" }));

    expect(screen.queryAllByRole("menuitemradio")).toEqual([]);
    expect(screen.queryByText("offline")).not.toBeInTheDocument();
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

  it("shows every level, Extra high and Max included, for Claude Code's default", async () => {
    const { user } = await openChat(session({ model: null, effort: null }));

    await user.click(screen.getByRole("button", { name: "Thinking: Thinking" }));

    expect(options(screen.getByRole("dialog", { name: "Thinking" }))).toEqual([
      "Low",
      "Medium",
      "High",
      "Extra high",
      "Max",
    ]);
  });

  it("names levels and modes this app does not know yet as the Mac sends them", async () => {
    const api = fakeApi();
    const list = modelList();
    list.models[1] = { ...defined(list.models[1]), effort_levels: ["low", "turbo"] };
    api.models.mockResolvedValue(list);
    const chat = session({ model: "opus", effort: null, permission_mode: "dontAsk" as never });
    const { user } = await openChat(chat, api);

    await user.click(screen.getByRole("button", { name: "Thinking: Thinking" }));

    expect(options(screen.getByRole("dialog", { name: "Thinking" }))).toEqual(["Low", "turbo"]);
    expect(screen.getByRole("button", { name: "Permission mode: dontAsk" })).toBeInTheDocument();
  });

  it("is not available for Haiku", async () => {
    await openChat(session({ model: "haiku", effort: null }));

    expect(screen.getByRole("button", { name: "Thinking: Not available" })).toBeDisabled();
  });

  it("follows the agent default model in a new chat", async () => {
    const api = fakeApi();
    api.agentDefaults.mockResolvedValue(agentDefaults({ model: "haiku" }));
    await newChat(api);

    expect(await screen.findByRole("button", { name: "Thinking: Not available" })).toBeDisabled();
  });

  it("drops a chosen level the new model does not take", async () => {
    const api = fakeApi();
    const { user } = await newChat(api);
    const pick = async (selector: string, option: RegExp) => {
      await user.click(screen.getByRole("button", { name: selector }));
      await user.click(screen.getByRole("menuitemradio", { name: option }));
    };

    await pick("Thinking: Thinking", /Extra high/);
    await pick("Model: Model", /^Opus 5.5/);
    expect(screen.getByRole("button", { name: "Thinking: Extra high" })).toBeInTheDocument();
    await pick("Model: Opus 5.5", /^Opus 4.6/);
    expect(screen.getByRole("button", { name: "Thinking: Thinking" })).toBeInTheDocument();
    await pick("Thinking: Thinking", /Max/);
    await pick("Model: Opus 4.6", /^Haiku/);
    expect(screen.getByRole("button", { name: "Thinking: Not available" })).toBeDisabled();
    await pick("Model: Haiku 4.5", /agent default/);
    await user.type(screen.getByLabelText("Message"), "Go{Enter}");

    expect(api.createSession).toHaveBeenCalledWith({
      repo: "todo-ui",
      prompt: "Go",
      attachment_ids: [],
    });
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

    expect(await permissions()).toHaveLength(5);
    await user.click(screen.getByRole("button", { name: "Model: Model" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Opus 5.5/ }));
    expect(await permissions()).toHaveLength(6);
    await user.click(screen.getByRole("button", { name: "Permission mode: Mode" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Auto/ }));
    await user.click(screen.getByRole("button", { name: "Permission mode: Auto" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Accept edits/ }));
    await user.click(screen.getByRole("button", { name: "Model: Opus 5.5" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Haiku/ }));
    expect(
      screen.getByRole("button", { name: "Permission mode: Accept edits" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Model: Haiku 4.5" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Opus 5.5/ }));
    await user.click(screen.getByRole("button", { name: "Permission mode: Accept edits" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Auto/ }));
    await user.click(screen.getByRole("button", { name: "Model: Opus 5.5" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Haiku/ }));
    // Haiku does not take Auto: the new chat goes back to the agent default.
    expect(screen.getByRole("button", { name: "Permission mode: Mode" })).toBeInTheDocument();
  });
});
