import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Session } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { ApiError } from "../../api/client.ts";
import { claudeChat, connector, detail, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

// Commands the SDK cannot run open Nest's own screens instead (B59).

async function openChat(chats: Session[] = [session()], api: FakeApi = fakeApi()) {
  const chat = defined(chats[0]);
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : chats));
  api.session.mockImplementation((id) =>
    Promise.resolve(detail(chats.find((c) => c.id === id) ?? chat)),
  );
  api.updateSession.mockImplementation((_id, body) => Promise.resolve({ ...chat, ...body }));
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  await waitFor(() => {
    expect(api.models).toHaveBeenCalled();
  });
  return { ...rendered, field: screen.getByLabelText("Message") };
}

async function newChat(api: FakeApi = fakeApi()) {
  api.repos.mockResolvedValue([repo("cv-page")]);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: "New chat in cv-page" }));
  await waitFor(() => {
    expect(api.models).toHaveBeenCalled();
  });
  return { ...rendered, field: screen.getByLabelText("Message") };
}

const options = () =>
  within(screen.getByRole("listbox", { name: "Commands" }))
    .getAllByRole("option")
    .map((o) => o.textContent);

describe("Nest's own slash commands", () => {
  it("are suggested with what they do, among the chat's commands", async () => {
    const { user, field } = await openChat();

    await user.type(field, "/m");

    await screen.findByRole("listbox", { name: "Commands" });
    expect(options()).toEqual([
      "/mcpShow MCP servers and connectors",
      "/model [model]Set the model for this chat",
      "/compact [focus]Summarise the conversation",
      "/permissionsChoose the permission mode",
      "/resume [search]Resume another chat",
    ]);
  });

  it("are suggested even when the chat's commands cannot be loaded", async () => {
    const api = fakeApi();
    api.sessionCommands.mockRejectedValue(new Error("boom"));
    const { user, field } = await openChat([session()], api);

    await user.type(field, "/res");

    expect(await screen.findByRole("option", { name: /^\/resume/ })).toBeInTheDocument();
  });

  it("/model opens the model picker instead of sending", async () => {
    const { user, field, api } = await openChat();

    await user.type(field, "/model{Enter}");
    // Enter first completes the suggestion, which runs the command.
    const sheet = await screen.findByRole("dialog", { name: "Model" });

    expect(within(sheet).getByRole("menuitemradio", { name: /^Opus 5.5/ })).toBeInTheDocument();
    expect(field).toHaveValue("");
    expect(api.sendMessage).not.toHaveBeenCalled();
  });

  it("/model with a name sets the model directly, by its id or its name", async () => {
    const { user, field, api } = await openChat();

    await user.type(field, "/model haiku ");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => {
      expect(api.updateSession).toHaveBeenCalledWith("s1", { model: "haiku" });
    });
    expect(field).toHaveValue("");

    await user.type(field, "/model opus 4.6");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => {
      expect(api.updateSession).toHaveBeenCalledWith("s1", { model: "claude-opus-4-6" });
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.sendMessage).not.toHaveBeenCalled();
  });

  it("/model with a name it does not know opens the picker", async () => {
    const { user, field, api } = await openChat();

    await user.type(field, "/model gpt");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("dialog", { name: "Model" })).toBeInTheDocument();
    expect(api.updateSession).not.toHaveBeenCalled();
  });

  it("/model with a name opens the picker while the models are not known", async () => {
    const api = fakeApi();
    api.models.mockRejectedValue(new ApiError(500, "no models"));
    const { user, field } = await openChat([session()], api);

    await user.type(field, "/model haiku");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("dialog", { name: "Model" })).toBeInTheDocument();
    expect(api.updateSession).not.toHaveBeenCalled();
  });

  it("/permissions opens the permission mode picker", async () => {
    const { user, field, api } = await openChat();

    await user.type(field, "/permissions");
    await user.click(screen.getByRole("button", { name: "Send" }));

    const sheet = await screen.findByRole("dialog", { name: "Permission mode" });
    await user.click(within(sheet).getByRole("menuitemradio", { name: /^Plan/ }));
    expect(api.updateSession).toHaveBeenCalledWith("s1", { permission_mode: "plan" });
    expect(api.sendMessage).not.toHaveBeenCalled();
  });

  it("/mcp shows the connectors with how to sign in", async () => {
    const api = fakeApi();
    api.connectors.mockResolvedValue([
      connector({ name: "claude.ai Slack", display_name: "Slack", status: "needs-auth" }),
    ]);
    const { user, field } = await openChat([session()], api);

    await user.type(field, "/mc");
    await user.click(await screen.findByRole("option", { name: /^\/mcp/ }));

    const sheet = await screen.findByRole("dialog", { name: "Connectors" });
    expect(api.connectors).toHaveBeenCalled();
    // Open, so what needs the user shows at once.
    const group = await within(sheet).findByRole("region", { name: /claude\.ai connectors/ });
    expect(within(group).getByText("Slack")).toBeInTheDocument();
    expect(within(group).getByText("Needs sign-in")).toBeInTheDocument();
    expect(field).toHaveValue("");

    await user.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("/mcp says when the connectors cannot be loaded", async () => {
    const api = fakeApi();
    api.connectors.mockRejectedValue(new ApiError(500, "registry broke"));
    const { user, field } = await openChat([session()], api);

    await user.type(field, "/mcp");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("registry broke")).toBeInTheDocument();
    const sheet = screen.getByRole("dialog", { name: "Connectors" });
    expect(within(sheet).getByText("Loading...")).toBeInTheDocument();
  });

  it("/resume lists the project's other chats and opens one", async () => {
    const other = session({
      id: "s2",
      title: "Add a dark theme",
      updated_at: "2026-10-01T00:00:00Z",
    });
    const older = session({
      id: "s3",
      title: "Fix the footer",
      updated_at: "2026-09-01T00:00:00Z",
    });
    const elsewhere = session({ id: "s4", repo: "notes", title: "Elsewhere" });
    const { user, field } = await openChat([session(), older, other, elsewhere]);

    await user.type(field, "/resume");
    await user.click(screen.getByRole("button", { name: "Send" }));

    const sheet = await screen.findByRole("dialog", { name: "Resume a chat" });
    const rows = within(sheet).getAllByRole("button", { name: /Add a dark theme|Fix the footer/ });
    expect(rows.map((row) => row.textContent)).toEqual(["Add a dark theme", "Fix the footer"]);
    expect(within(sheet).queryByText("Elsewhere")).toBeNull();
    expect(within(sheet).queryByText("Validate contact form")).toBeNull();

    await user.click(within(sheet).getByRole("button", { name: "Add a dark theme" }));
    expect(await screen.findByRole("region", { name: "Add a dark theme" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("/resume with words searches every chat, and a hit opens where it is", async () => {
    const api = fakeApi();
    api.search.mockResolvedValue({
      hits: [
        {
          session_id: "c1",
          repo: "cv-page",
          title: "Tune the hero section",
          event_id: null,
          ts: "2026-10-01T00:00:00Z",
          kind: "claude_chat",
          snippet: "the [[hero]] height",
        },
      ],
      indexing: false,
    });
    api.claudeChats.mockResolvedValue([claudeChat()]);
    api.claudeChatEvents.mockResolvedValue([]);
    const { user, field } = await openChat([session()], api);

    await user.type(field, "/resume hero");
    await user.click(screen.getByRole("button", { name: "Send" }));

    const sheet = await screen.findByRole("dialog", { name: "Resume a chat" });
    expect(within(sheet).getByRole("searchbox", { name: "Search chats" })).toHaveValue("hero");
    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith("hero");
    });
    await user.click(await within(sheet).findByRole("button", { name: /the hero height/ }));
    expect(
      await screen.findByRole("heading", { name: "Tune the hero section" }),
    ).toBeInTheDocument();
  });

  it("/resume says when there is no other chat", async () => {
    const { user, field } = await openChat();

    await user.type(field, "/resume");
    await user.click(screen.getByRole("button", { name: "Send" }));

    const sheet = await screen.findByRole("dialog", { name: "Resume a chat" });
    expect(within(sheet).getByText("No other chats in cv-page.")).toBeInTheDocument();
  });

  it("set a new chat's choices before its first message", async () => {
    const { user, field, api } = await newChat();

    await user.type(field, "/model haiku");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(screen.getByRole("button", { name: "Model: Haiku 4.5" })).toBeInTheDocument();

    await user.type(field, "/permissions");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("dialog", { name: "Permission mode" })).toBeInTheDocument();
    expect(api.createSession).not.toHaveBeenCalled();
  });

  it("other commands are still sent to Claude", async () => {
    const { user, field, api } = await openChat();

    await user.type(field, "/models are great");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledWith("s1", "/models are great", []);
    });
  });
});
