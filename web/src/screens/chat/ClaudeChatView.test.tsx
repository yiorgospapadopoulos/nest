import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { ClaudeChat, HarnessEvent, JsonObject, Session } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { claudeChat, detail, event, repo, session } from "../../test/fixtures.ts";
import { memoryStorage, renderApp } from "../../test/render.tsx";

const HISTORY: HarnessEvent[] = [
  event({
    id: 1,
    session_id: "c1",
    type: "session.user_message",
    payload: { text: "Make the hero taller", attachments: [] },
  }),
  event({
    id: 2,
    session_id: "c1",
    type: "session.message",
    payload: {
      parent_tool_use_id: null,
      blocks: [
        { type: "text", text: "Raised it to 80vh." },
        {
          type: "tool_use",
          id: "t1",
          name: "Edit",
          input: { file_path: "/Users/me/todo-ui/a.css" },
        },
      ],
    },
  }),
];

async function setup(chats: ClaudeChat[] = [claudeChat()], sessions: Session[] = []) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("todo-ui")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : sessions));
  api.claudeChats.mockResolvedValue(chats);
  api.claudeChatEvents.mockResolvedValue(HISTORY);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  return rendered;
}

describe("Claude Code chats", () => {
  it("are listed among the idle chats with a marker", async () => {
    await setup(
      [
        claudeChat(),
        claudeChat({ id: "c2", title: "Open one", open_in_claude_code: true }),
        claudeChat({ id: "c3", repo: "other", title: "Elsewhere" }),
      ],
      [session({ updated_at: "2026-10-06T09:00:00Z" })],
    );

    const idle = screen.getByRole("heading", { name: /Idle/ });
    expect(idle).toHaveTextContent("Idle3");
    const rows = within(screen.getByRole("region", { name: /Idle/ })).getAllByRole("button", {
      name: /, (Idle|Claude Code chat)/,
    });
    expect(rows.map((r) => r.getAttribute("aria-label"))).toEqual([
      "Tune the hero section, Claude Code chat",
      "Open one, Claude Code chat, open in Claude Code",
      "Validate contact form, Idle",
    ]);
    expect(screen.getAllByText("Claude Code")).toHaveLength(2);
    expect(screen.queryByText("Elsewhere")).not.toBeInTheDocument();
  });

  it("show their history read only and continue in harness", async () => {
    const { user, api } = await setup([claudeChat({ worktree: "agent-x" })]);
    const adopted = session({
      id: "s9",
      title: "Tune the hero section",
      provider_session_id: "c1",
    });
    api.adoptClaudeChat.mockResolvedValue(adopted);
    api.session.mockResolvedValue(detail(adopted));

    await user.click(screen.getByRole("button", { name: /Tune the hero section, Claude Code/ }));
    const view = within(await screen.findByRole("region", { name: "Tune the hero section" }));

    expect(await view.findByText("Make the hero taller")).toBeInTheDocument();
    expect(view.getByText("Raised it to 80vh.")).toBeInTheDocument();
    expect(view.getByText("a.css")).toBeInTheDocument();
    expect(view.getByText("Claude Code chat")).toBeInTheDocument();
    expect(view.getByText("agent-x")).toBeInTheDocument();
    expect(view.getByText(/Read only/)).toBeInTheDocument();
    expect(view.queryByLabelText("Message")).not.toBeInTheDocument();
    expect(api.claudeChatEvents).toHaveBeenCalledWith("c1");

    await user.click(view.getByRole("button", { name: "Continue in harness" }));

    expect(api.adoptClaudeChat).toHaveBeenCalledWith("c1");
    const chat = await screen.findByRole("region", { name: "Tune the hero section" });
    expect(await within(chat).findByLabelText("Message")).toBeInTheDocument();
    expect(api.session).toHaveBeenCalledWith("s9");
    await user.click(screen.getByRole("button", { name: "Back to todo-ui" }));
    expect(screen.getByRole("button", { name: /Tune the hero section, Idle/ })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Tune the hero section, Claude Code/ }),
    ).not.toBeInTheDocument();
  });

  it("say when the chat is open in Claude Code, and stay when continuing fails", async () => {
    const { user, api } = await setup([claudeChat({ open_in_claude_code: true })]);
    api.claudeChatEvents.mockResolvedValue([]);
    api.adoptClaudeChat.mockRejectedValue(new ApiError(409, "the folder of this chat is gone"));

    await user.click(screen.getByRole("button", { name: /Tune the hero section, Claude Code/ }));
    const view = within(await screen.findByRole("region", { name: "Tune the hero section" }));

    expect(await view.findByText("No messages yet")).toBeInTheDocument();
    expect(view.getByText("Open in Claude Code")).toBeInTheDocument();
    expect(view.getByText(/Close it there before sending/)).toBeInTheDocument();
    const button = view.getByRole("button", { name: "Continue in harness" });
    await user.click(button);
    expect(await screen.findByText("the folder of this chat is gone")).toBeInTheDocument();
    expect(button).toBeEnabled();
  });

  it("toast when the history cannot be read", async () => {
    const { user, api } = await setup();
    api.claudeChatEvents.mockRejectedValue(new ApiError(404, "unknown Claude Code chat"));

    await user.click(screen.getByRole("button", { name: /Tune the hero section, Claude Code/ }));

    expect(await screen.findByText("unknown Claude Code chat")).toBeInTheDocument();
    expect(await screen.findByText("No messages yet")).toBeInTheDocument();
  });

  it("are listed again when the Mac says they changed, closing one that went away", async () => {
    const { user, api, push } = await setup();
    await user.click(screen.getByRole("button", { name: /Tune the hero section, Claude Code/ }));
    await screen.findByRole("region", { name: "Tune the hero section" });
    api.claudeChats.mockResolvedValue([]);

    push({ type: "claude_chats.updated", payload: { repos: ["todo-ui"] } });

    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Tune the hero section" })).toBeNull();
    });
    expect(api.claudeChats).toHaveBeenCalledTimes(2);
    expect(screen.getByText("No chats yet")).toBeInTheDocument();
  });

  it("toast when they cannot be listed again", async () => {
    const { api, push } = await setup();
    api.claudeChats.mockRejectedValue(new ApiError(500, "listing failed"));

    push({ type: "claude_chats.updated", payload: { repos: ["todo-ui"] } });

    expect(await screen.findByText("listing failed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Tune the hero section/ })).toBeInTheDocument();
  });

  it("hide automated chats unless this device asks for them", async () => {
    const storage = memoryStorage();
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("todo-ui")]);
    const review = claudeChat({ id: "c9", title: "Security review", automated: true });
    api.claudeChats.mockImplementation((all) =>
      Promise.resolve(all === true ? [claudeChat(), review] : [claudeChat()]),
    );
    const first = await renderApp({ api, storage });
    await first.user.click(screen.getByRole("tab", { name: "Projects" }));

    const toggle = screen.getByRole("switch", { name: "Show automated chats" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(api.claudeChats).toHaveBeenLastCalledWith(false);
    expect(screen.queryByText("Security review")).not.toBeInTheDocument();

    await first.user.click(toggle);
    expect(await screen.findByText("Security review")).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(api.claudeChats).toHaveBeenLastCalledWith(true);
    first.unmount();

    const again = await renderApp({ api, storage });
    await again.user.click(screen.getByRole("tab", { name: "Projects" }));
    expect(screen.getByRole("switch", { name: "Show automated chats" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(await screen.findByText("Security review")).toBeInTheDocument();
    await again.user.click(screen.getByRole("switch", { name: "Show automated chats" }));
    await waitFor(() => {
      expect(screen.queryByText("Security review")).not.toBeInTheDocument();
    });
  });

  it("can still be shown when this device cannot remember the choice", async () => {
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    } as unknown as Storage;
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("todo-ui")]);
    const { user } = await renderApp({ api, storage: broken });
    await user.click(screen.getByRole("tab", { name: "Projects" }));

    await user.click(screen.getByRole("switch", { name: "Show automated chats" }));

    expect(api.claudeChats).toHaveBeenLastCalledWith(true);
  });

  it("open the session when the chat was continued on another device", async () => {
    const { user, api, push } = await setup();
    await user.click(screen.getByRole("button", { name: /Tune the hero section, Claude Code/ }));
    await screen.findByRole("region", { name: "Tune the hero section" });
    const adopted = session({ id: "s7", title: "Continued", provider_session_id: "c1" });
    api.session.mockResolvedValue(detail(adopted));
    api.claudeChats.mockResolvedValue([]);

    push({
      id: 50,
      type: "session.created",
      session_id: "s7",
      payload: { session: adopted as unknown as JsonObject },
    });
    push({ type: "claude_chats.updated", payload: { repos: ["todo-ui"] } });

    expect(await screen.findByRole("region", { name: "Continued" })).toBeInTheDocument();
  });
});
