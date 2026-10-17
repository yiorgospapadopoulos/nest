import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { ClaudeChat, NestEvent, JsonObject, Session } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { claudeChat, detail, event, repo, session } from "../../test/fixtures.ts";
import { memoryStorage, renderApp } from "../../test/render.tsx";
import { defined } from "../../test/defined.ts";

const HISTORY: NestEvent[] = [
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
          input: { file_path: "/Users/me/cv-page/a.css" },
        },
      ],
    },
  }),
];

async function setup(chats: ClaudeChat[] = [claudeChat()], sessions: Session[] = []) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : sessions));
  api.claudeChats.mockResolvedValue(chats);
  api.claudeChatEvents.mockResolvedValue(HISTORY);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  return rendered;
}

describe("Claude Code chats", () => {
  it("are listed among the idle chats", async () => {
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
      "Tune the hero section, Claude Code chat, on main",
      "Open one, Claude Code chat, open in Claude Code, on main",
      "Validate contact form, Idle, worktree agent/contact",
    ]);
    // Open in Claude Code is not work in Nest: a plain dot, no fireflies or glow (B80).
    const open = defined(rows[1]);
    expect(open.firstElementChild).toHaveClass("dot s-run");
    expect(open.querySelector(".ff")).toBeNull();
    expect(open).not.toHaveClass("rglow");
    // No "Claude Code" marker: a row shows only where the chat works (B55).
    expect(screen.queryByText("Claude Code")).not.toBeInTheDocument();
    expect(screen.queryByText("Elsewhere")).not.toBeInTheDocument();
  });

  it("show their history read only and continue in Nest", async () => {
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
    expect(view.getByRole("img", { name: "Claude Code chat" })).toHaveClass("dot s-idle");
    expect(view.getByText("agent-x")).toBeInTheDocument();
    expect(view.getByText(/Read only/)).toBeInTheDocument();
    expect(view.queryByLabelText("Message")).not.toBeInTheDocument();
    expect(api.claudeChatEvents).toHaveBeenCalledWith("c1");

    await user.click(view.getByRole("button", { name: "Continue in Nest" }));

    expect(api.adoptClaudeChat).toHaveBeenCalledWith("c1");
    const chat = await screen.findByRole("region", { name: "Tune the hero section" });
    expect(await within(chat).findByLabelText("Message")).toBeInTheDocument();
    expect(api.session).toHaveBeenCalledWith("s9");
    await user.click(screen.getByRole("button", { name: "Back to cv-page" }));
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
    // Nothing runs in Nest: the run tone stays a plain dot, not the fireflies (B80).
    expect(view.getByRole("img", { name: "Open in Claude Code" })).toHaveClass("dot s-run");
    expect(view.getByText(/Close it there before sending/)).toBeInTheDocument();
    const button = view.getByRole("button", { name: "Continue in Nest" });
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

    push({ type: "claude_chats.updated", payload: { repos: ["cv-page"] } });

    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Tune the hero section" })).toBeNull();
    });
    expect(api.claudeChats).toHaveBeenCalledTimes(2);
    expect(screen.getByText("No chats yet")).toBeInTheDocument();
  });

  it("toast when they cannot be listed again", async () => {
    const { api, push } = await setup();
    api.claudeChats.mockRejectedValue(new ApiError(500, "listing failed"));

    push({ type: "claude_chats.updated", payload: { repos: ["cv-page"] } });

    expect(await screen.findByText("listing failed")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Tune the hero section, Claude Code/ }),
    ).toBeInTheDocument();
  });

  it("hide automated chats unless this device asks for them", async () => {
    const storage = memoryStorage();
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("cv-page")]);
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
    api.repos.mockResolvedValue([repo("cv-page")]);
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
    push({ type: "claude_chats.updated", payload: { repos: ["cv-page"] } });

    expect(await screen.findByRole("region", { name: "Continued" })).toBeInTheDocument();
  });

  it("archive and unarchive from the list, folding into Archived", async () => {
    const shelved = claudeChat({ id: "c2", title: "Old idea", archived: true });
    const { user, api } = await setup([claudeChat(), shelved]);
    api.setClaudeChatArchived.mockImplementation((id, archived) =>
      Promise.resolve(
        claudeChat({ id, title: id === "c1" ? "Tune the hero section" : "Old idea", archived }),
      ),
    );
    const folder = screen.getByRole("button", { name: /Archived/ });
    expect(folder).toHaveAttribute("aria-expanded", "false");
    expect(folder).toHaveTextContent("Archived1");
    expect(screen.queryByText("Old idea")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Actions for Tune the hero section" }));
    const sheet = screen.getByRole("dialog", { name: "Actions for Tune the hero section" });
    await user.click(within(sheet).getByRole("menuitem", { name: "Archive" }));

    expect(api.setClaudeChatArchived).toHaveBeenLastCalledWith("c1", true);
    expect(await screen.findByText("Archived Tune the hero section")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Idle/ })).not.toBeInTheDocument();
    expect(folder).toHaveTextContent("Archived2");

    await user.click(folder);
    fireEvent.contextMenu(screen.getByRole("button", { name: /Old idea, Claude Code chat/ }));
    await user.click(screen.getByRole("menuitem", { name: "Unarchive" }));

    expect(api.setClaudeChatArchived).toHaveBeenLastCalledWith("c2", false);
    expect(await screen.findByText("Unarchived Old idea")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Idle/ })).toHaveTextContent("Idle1");
  });

  it("keep the actions open when archiving fails", async () => {
    const { user, api } = await setup();
    api.setClaudeChatArchived.mockRejectedValue(new ApiError(404, "unknown Claude Code chat"));

    await user.click(screen.getByRole("button", { name: "Actions for Tune the hero section" }));
    await user.click(screen.getByRole("menuitem", { name: "Archive" }));

    expect(await screen.findByText("unknown Claude Code chat")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("move to Archived when another device archives one", async () => {
    const { api, push } = await setup();
    api.claudeChats.mockResolvedValue([claudeChat({ archived: true })]);

    push({ type: "claude_chats.updated", payload: { repos: ["cv-page"] } });

    expect(await screen.findByRole("button", { name: /Archived/ })).toHaveTextContent("Archived1");
    expect(screen.queryByText("Tune the hero section")).not.toBeInTheDocument();
  });
});
