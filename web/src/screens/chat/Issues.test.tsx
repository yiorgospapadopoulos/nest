import { act, fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { IssueList, IssueSummary, Session } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { detail, NOW, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";
import { ISSUES_EVERY_MS } from "./start.ts";

function issue(overrides: Partial<IssueSummary> = {}): IssueSummary {
  return {
    number: 47,
    title: "Theme choice is forgotten after a reload",
    url: "https://github.com/me/todo-ui/issues/47",
    labels: ["bug"],
    comments: 3,
    updated_at: NOW,
    prs: [{ number: 49, url: "https://github.com/me/todo-ui/pull/49" }],
    chat: null,
    ...overrides,
  };
}

async function newChat(list: IssueList | Error, sessions: Session[] = []) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("todo-ui")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : sessions));
  api.session.mockImplementation((id) =>
    Promise.resolve(detail(sessions.find((s) => s.id === id))),
  );
  if (list instanceof Error) api.issues.mockRejectedValue(list);
  else api.issues.mockResolvedValue(list);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: "New chat in todo-ui" }));
  return { ...rendered, api, page: within(screen.getByRole("region", { name: "New chat" })) };
}

const row = (title: RegExp) => screen.getByRole("button", { name: title });

describe("open issues on the new chat screen (B101)", () => {
  it("starts a chat from an issue without a chat, with the issue as its first message", async () => {
    const { user, api, page } = await newChat({ available: true, show: "all", issues: [issue()] });
    const section = within(await page.findByRole("region", { name: "Open issues" }));

    expect(section.getByText("#47 · PR #49 · bug · 3 comments")).toBeInTheDocument();
    await user.click(row(/^Theme choice/));
    expect(
      page.getByText("Issue #47 will be the first message. Add anything, or press send"),
    ).toBeInTheDocument();
    await user.click(page.getByRole("button", { name: "Send" }));

    expect(api.createSession).toHaveBeenCalledWith(
      expect.objectContaining({ repo: "todo-ui", prompt: "", issue: 47 }),
    );
  });

  it("opens the chat an issue already has, and starts a new one on a long-press", async () => {
    const chat = session({ id: "s7", title: "Fix the theme", issue: issue() });
    const { user, api, page } = await newChat(
      { available: true, show: "all", issues: [issue({ chat: "s7" })] },
      [chat],
    );
    await page.findByRole("region", { name: "Open issues" });

    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      fireEvent.pointerDown(row(/^Theme choice/), { button: 0, clientX: 0, clientY: 0 });
      await act(() => vi.advanceTimersByTimeAsync(600));
      fireEvent.pointerUp(row(/^Theme choice/));
      fireEvent.click(row(/^Theme choice/));
    } finally {
      vi.useRealTimers();
    }
    expect(page.getByText(/Issue #47 will be the first message/)).toBeInTheDocument();
    expect(api.createSession).not.toHaveBeenCalled();

    await user.click(row(/^Theme choice/));
    expect(await screen.findByRole("region", { name: "Fix the theme" })).toBeInTheDocument();
  });

  it("keeps All or Mine per project", async () => {
    const { user, api, page } = await newChat({ available: true, show: "all", issues: [issue()] });
    await page.findByRole("region", { name: "Open issues" });
    expect(api.issues).toHaveBeenLastCalledWith("todo-ui", undefined);

    await user.click(page.getByRole("button", { name: "Mine" }));
    expect(api.issues).toHaveBeenLastCalledWith("todo-ui", "mine");
    await user.click(screen.getByRole("button", { name: "Back to todo-ui" }));
    await user.click(screen.getByRole("button", { name: "New chat in todo-ui" }));
    expect(api.issues).toHaveBeenLastCalledWith("todo-ui", "mine");
  });

  it("reads the list again every minute and when the page shows again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { api, page } = await newChat({ available: true, show: "all", issues: [issue()] });
      await page.findByRole("region", { name: "Open issues" });
      const reads = api.issues.mock.calls.length;

      await act(() => vi.advanceTimersByTimeAsync(ISSUES_EVERY_MS));
      expect(api.issues.mock.calls.length).toBe(reads + 1);
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      expect(api.issues.mock.calls.length).toBe(reads + 2);
    } finally {
      vi.useRealTimers();
    }
  });

  it.each([
    ["without a GitHub remote", { available: false, show: "all" as const, issues: [] }],
    ["when GitHub fails", new ApiError(502, "gh failed")],
  ])("leaves the section out %s", async (_, list) => {
    const { page, api } = await newChat(list);

    await vi.waitFor(() => {
      expect(api.issues).toHaveBeenCalled();
    });
    expect(page.queryByRole("region", { name: "Open issues" })).not.toBeInTheDocument();
    expect(screen.queryByText("gh failed")).not.toBeInTheDocument();
  });
});
