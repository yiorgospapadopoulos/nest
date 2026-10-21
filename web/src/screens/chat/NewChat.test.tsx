import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Approval, Session } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { approval, detail, NOW, question, repo, review, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";
import { QUESTION_COUNT } from "./start.ts";

const minutesAgo = (minutes: number) => new Date(Date.parse(NOW) - minutes * 60_000).toISOString();

async function newChat(sessions: Session[] = [], approvals: Approval[] = []) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : sessions));
  api.approvals.mockResolvedValue(approvals);
  api.session.mockImplementation((id) =>
    Promise.resolve(detail(sessions.find((s) => s.id === id))),
  );
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: "New chat in cv-page" }));
  return { ...rendered, api, page: within(screen.getByRole("region", { name: "New chat" })) };
}

describe("the new chat screen (B90 design I, B102)", () => {
  it("asks about the project in large type, with no header or starters", async () => {
    const { page } = await newChat();

    expect(page.getByRole("heading", { level: 2 })).toHaveTextContent(/\bcv-page\b.*\?$/);
    expect(page.getByText("cv-page", { selector: ".nc-who" })).toBeVisible();
    expect(page.queryByText("New chat")).not.toBeInTheDocument();
    expect(page.queryByText(/Describe the task/)).not.toBeInTheDocument();
    expect(page.getByPlaceholderText("Ask, build, / for commands…")).toBe(
      page.getByLabelText("Message"),
    );
    // Nothing waits and nothing is recent: no lists.
    expect(page.queryByRole("region", { name: "Waiting on you" })).not.toBeInTheDocument();
    expect(page.queryByRole("region", { name: "Recent" })).not.toBeInTheDocument();
  });

  it("closes with Escape", async () => {
    const { user } = await newChat();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("region", { name: "New chat" })).not.toBeInTheDocument();
  });

  it("asks the next question each time it appears, never the same twice in a row", async () => {
    const { user, page } = await newChat();
    const asked = [page.getByRole("heading", { level: 2 }).textContent];
    for (let i = 0; i < QUESTION_COUNT; i++) {
      await user.click(screen.getByRole("button", { name: "Back to cv-page" }));
      await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));
      asked.push(screen.getByRole("heading", { level: 2 }).textContent);
    }

    expect(asked.every((q, i) => i === 0 || q !== asked[i - 1])).toBe(true);
    expect(new Set(asked).size).toBe(QUESTION_COUNT);
  });

  it("lists the first three things waiting on the user, then how many more", async () => {
    const chats = ["a", "b", "c", "d"].map((id) => session({ id, title: `Chat ${id}` }));
    const waiting = [
      approval({ id: "p1", session_id: "a" }),
      question({ id: "p2", session_id: "b" }),
      review({ id: "p3", session_id: "c" }),
      approval({ id: "p4", session_id: "d" }),
    ];
    const { user, page } = await newChat(chats, waiting);
    const list = within(page.getByRole("region", { name: "Waiting on you" }));

    expect(list.getByRole("heading")).toHaveTextContent("Waiting on you · 4");
    const rows = () => list.getAllByRole("button").filter((b) => b.className === "nc-w");
    expect(rows().map((r) => r.textContent)).toEqual([
      "Chat aPermission · Bash npm install zod",
      "Chat bQuestion · DAG or tree?",
      "Chat cReady for review · +48 -19 in 3 files",
    ]);
    await user.click(list.getByRole("button", { name: "1 more" }));
    expect(rows()).toHaveLength(4);
    expect(list.queryByRole("button", { name: "1 more" })).not.toBeInTheDocument();

    await user.click(defined(rows()[1]));
    expect(await screen.findByRole("region", { name: "Chat b" })).toBeInTheDocument();
  });

  it("lists the project's latest chats under Recent with their age", async () => {
    const chats = [
      session({ id: "a", title: "Update publications", updated_at: minutesAgo(9) }),
      session({ id: "b", title: "Add thumbnails", updated_at: minutesAgo(2 * 1440) }),
    ];
    const { user, page } = await newChat(chats);
    const recent = within(page.getByRole("region", { name: "Recent" }));

    expect(recent.getAllByRole("button").map((b) => b.textContent)).toEqual([
      expect.stringMatching(/^Update publications\d+[mhd]$/),
      expect.stringMatching(/^Add thumbnails\d+d$/),
    ]);
    await user.click(recent.getByRole("button", { name: /^Add thumbnails/ }));
    expect(await screen.findByRole("region", { name: "Add thumbnails" })).toBeInTheDocument();
  });
});
