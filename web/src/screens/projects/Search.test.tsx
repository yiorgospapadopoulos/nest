import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { SearchHit } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { claudeChat, event, NOW, pixie, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

function hit(overrides: Partial<SearchHit> = {}): SearchHit {
  return {
    session_id: "s1",
    repo: "cv-page",
    title: "Validate contact form",
    event_id: 3,
    ts: NOW,
    kind: "assistant",
    snippet: "The [[login]] form is fixed",
    ...overrides,
  };
}

const message = (id: number, text: string) =>
  event({
    id,
    type: "session.message",
    payload: { blocks: [{ type: "text", text }], parent_tool_use_id: null },
  });

async function openProjects(hits: SearchHit[] = [], indexing = false) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) =>
    Promise.resolve(archived ? [] : [session(), session({ id: "s2", title: "Other chat" })]),
  );
  api.claudeChats.mockResolvedValue([claudeChat()]);
  api.search.mockResolvedValue({ hits, indexing });
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  return rendered;
}

const field = () => screen.getByRole("searchbox", { name: "Search chats" });

describe("search", () => {
  const scroll = vi.fn();

  beforeEach(() => {
    // jsdom does not lay out pages.
    Element.prototype.scrollIntoView = scroll;
  });

  it("shows hits grouped by chat with highlighted matches", async () => {
    const { user, api } = await openProjects([
      hit({ event_id: 5, kind: "user", snippet: "Fix the [[login]] bug" }),
      hit({
        session_id: "s2",
        title: "Other chat",
        event_id: null,
        kind: "title",
        snippet: "[[Login]] page",
      }),
      hit({ event_id: 9, kind: "tool", snippet: "Bash grep [[login]]" }),
      hit({
        session_id: "s2",
        title: "Other chat",
        event_id: 12,
        kind: "tool_result",
        snippet: "[[login]] ok",
      }),
    ]);

    await user.type(field(), "login");

    const results = await screen.findByLabelText("Search results");
    expect(api.search).toHaveBeenCalledTimes(1);
    expect(api.search).toHaveBeenCalledWith("login");
    const first = within(results).getByRole("region", { name: "Validate contact form" });
    expect(
      within(first)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Validate contact formcv-page", "YouFix the login bug", "ToolBash grep login"]);
    expect(within(first).getAllByText("login", { selector: "mark" })).toHaveLength(2);
    const second = within(results).getByRole("region", { name: "Other chat" });
    expect(within(second).getByText("Login", { selector: "mark" })).toBeInTheDocument();
    expect(within(second).getByText("Output")).toBeInTheDocument();
    // The project lists are hidden while searching.
    expect(screen.queryByRole("button", { name: /^Other chat, Idle/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(field()).toHaveValue("");
    expect(screen.getByRole("button", { name: /^Other chat, Idle/ })).toBeInTheDocument();
  });

  it("opens the chat at the hit, highlighted until its animation ends", async () => {
    const { user, api } = await openProjects([
      hit({ event_id: 3 }),
      hit({ event_id: 6, kind: "tool_result" }),
    ]);
    api.sessionEvents.mockResolvedValue([
      event({ id: 1, type: "session.user_message", payload: { text: "Start", attachments: [] } }),
      message(3, "The login form is fixed"),
      message(4, "Next"),
      message(7, "Later"),
    ]);

    await user.type(field(), "login");
    await user.click(await screen.findByRole("button", { name: /^ClaudeThe login form/ }));

    // A reply renders as Markdown: its row, around the paragraph, takes the highlight.
    const target = defined((await screen.findByText("The login form is fixed")).closest(".m-a"));
    await waitFor(() => {
      expect(target).toHaveClass("hit");
    });
    expect(scroll).toHaveBeenCalledWith({ block: "center" });
    fireEvent.animationEnd(target);
    expect(target).not.toHaveClass("hit");
  });

  it("opens a tool result hit at the message shown before it", async () => {
    const { user, api } = await openProjects([hit({ event_id: 6, kind: "tool_result" })]);
    api.sessionEvents.mockResolvedValue([message(4, "Ran the tests"), message(7, "Later")]);

    await user.type(field(), "login");
    await user.click(await screen.findByRole("button", { name: /^Output/ }));

    const shown = defined((await screen.findByText("Ran the tests")).closest(".m-a"));
    await waitFor(() => {
      expect(shown).toHaveClass("hit");
    });
    expect(screen.getByText("Later").closest(".m-a")).not.toHaveClass("hit");
  });

  it("opens chats from title hits, and Claude Code chats read only", async () => {
    const { user } = await openProjects([
      hit({ event_id: null, kind: "title", snippet: "Validate [[contact]] form" }),
      hit({
        session_id: "c1",
        title: "Tune the hero section",
        event_id: null,
        kind: "claude_chat",
        snippet: "Tune the [[hero]] section",
      }),
    ]);

    await user.type(field(), "contact");
    await user.click(await screen.findByRole("button", { name: /cv-page · Claude Code/ }));
    expect(await screen.findByRole("button", { name: /Continue/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Back/ }));

    await user.click(await screen.findByRole("button", { name: /^Validate contact formcv-page$/ }));
    await waitFor(() => {
      expect(window.location.pathname).toBe("/chat/s1");
    });
    expect(document.querySelector(".hit")).toBeNull();
  });

  it("names a pixie's chat after its pixie and opens the pixie's page", async () => {
    const api = fakeApi();
    api.pixies.mockResolvedValue([pixie()]);
    api.search.mockResolvedValue({
      hits: [
        hit({ session_id: "c1", repo: "pixie:p1", title: "Tester", event_id: 4 }),
        hit({ session_id: "c2", repo: "pixie:gone", title: "Old", event_id: null }),
      ],
      indexing: false,
    });
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));

    await user.type(field(), "login");
    const results = await screen.findByLabelText("Search results");
    expect(within(results).queryByText(/pixie:/)).not.toBeInTheDocument();
    expect(within(results).getByText("Pixie")).toBeInTheDocument();
    const found = within(results).getByRole("region", { name: "Tester" });
    expect(found.querySelector(".sres-h svg")).not.toBeNull();
    await user.click(within(found).getByRole("button", { name: /^ClaudeThe login form/ }));

    expect(await screen.findByRole("tab", { name: "Chat", selected: true })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/pixie/p1");
  });

  it("says when nothing matches, while older chats are indexed, or when search fails", async () => {
    const { user, api } = await openProjects([], true);

    await user.type(field(), "zebra");
    expect(await screen.findByText("No chats match.")).toBeInTheDocument();
    expect(screen.getByText("Still indexing older chats on your Mac.")).toBeInTheDocument();

    api.search.mockRejectedValueOnce(new ApiError(500, "database is locked"));
    await user.type(field(), "s");
    expect(await screen.findByText("Search is not available right now.")).toBeInTheDocument();
    expect(screen.getByText("database is locked")).toBeInTheDocument();
  });

  it("only asks once typing pauses and shows the latest answer", async () => {
    const { user, api } = await openProjects();
    let answer: (value: { hits: SearchHit[]; indexing: boolean }) => void = () => undefined;
    api.search.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          answer = resolve;
        }),
    );

    await user.type(field(), "lo");
    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith("lo");
    });
    expect(screen.getByText("Searching…")).toBeInTheDocument();
    await user.type(field(), "gin");
    expect(await screen.findByText("No chats match.")).toBeInTheDocument();
    answer({ hits: [hit()], indexing: false });

    await waitFor(() => {
      expect(api.search).toHaveBeenLastCalledWith("login");
    });
    expect(api.search).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("region", { name: "Validate contact form" })).not.toBeInTheDocument();
  });
});

describe("stuck chats in the list", () => {
  it("carry a badge with the reason", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("cv-page")]);
    api.sessions.mockImplementation((archived) =>
      Promise.resolve(
        archived
          ? []
          : [
              session({
                state: "running",
                stuck: { reason: "repeating", since: NOW, details: "Called Bash 5 times" },
              }),
            ],
      ),
    );
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));

    const row = screen.getByRole("button", { name: /Validate contact form, Running, stuck/ });
    expect(within(row).getByText("Stuck")).toHaveAttribute("title", "Called Bash 5 times");
  });
});
