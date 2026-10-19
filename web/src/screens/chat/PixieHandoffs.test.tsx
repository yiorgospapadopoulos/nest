import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { NestEvent, Session } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { check, detail, event, pixie, prStatus, repo, session } from "../../test/fixtures.ts";
import { openPixie } from "../../test/pixies.ts";
import { renderApp } from "../../test/render.tsx";

const tester = pixie({ id: "p1", name: "Tester", mascot: "moth", chat_session_id: "pc" });
const pixieChat = session({ id: "pc", title: "Tester", repo: "pixie:p1", pixie_id: "p1" });

/** The app with these project chats, and the events of whichever chat is opened. */
function withChats(chats: Session[], events: Record<string, NestEvent[]> = {}): FakeApi {
  const api = fakeApi();
  api.pixies.mockResolvedValue([tester]);
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : chats));
  api.session.mockImplementation((id) =>
    Promise.resolve(detail(id === "pc" ? pixieChat : chats.find((c) => c.id === id))),
  );
  api.sessionEvents.mockImplementation((id) => Promise.resolve(events[id] ?? []));
  return api;
}

const card = (id: number, kind: string, sessionId: string) =>
  event({ id, session_id: "pc", type: "pixie.card", payload: { kind, session_id: sessionId } });

describe("chats a pixie started (B41)", () => {
  it("say who started them in the list and the chat header", async () => {
    const api = withChats([
      session({ id: "s1", title: "Check the form", started_by_pixie: "p1" }),
      session({ id: "s2", title: "Old check", started_by_pixie: "gone" }),
      session({ id: "s3", title: "Mine" }),
    ]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));

    const started = screen.getByRole("button", { name: /^Check the form,/ });
    expect(started).toHaveAccessibleName(
      "Check the form, Idle, Started by Tester, worktree agent/contact",
    );
    expect(within(started).getByText("Started by Tester")).toBeInTheDocument();
    expect(within(started).getByRole("img", { hidden: true, name: "moth" })).toBeInTheDocument();
    const old = screen.getByRole("button", { name: /^Old check,/ });
    expect(within(old).getByText("Started by a pixie")).toBeInTheDocument();
    expect(within(old).queryByRole("img", { hidden: true })).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("button", { name: /^Mine,/ })).queryByText(/Started by/),
    ).not.toBeInTheDocument();

    await user.click(started);
    const chat = await screen.findByRole("region", { name: "Check the form" });
    expect(within(chat).getByText("Started by Tester")).toBeInTheDocument();
  });
});

describe("pixie messages in a transcript (B41)", () => {
  it("names the pixie above a message it sent, and shows a report-back as a row", async () => {
    const api = withChats([session({ id: "s1", title: "Check the form" })], {
      s1: [
        event({
          id: 1,
          type: "session.user_message",
          payload: { text: "Run it", from_pixie: "p1" },
        }),
        event({ id: 2, type: "session.user_message", payload: { text: "Again", from_pixie: "x" } }),
        event({
          id: 3,
          type: "session.user_message",
          payload: { text: "- Check (cv-page): failed", origin: "report_back" },
        }),
      ],
    });
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: /^Check the form,/ }));

    const from = await screen.findByText("from Tester");
    expect(from.parentElement).toHaveClass("m-from");
    expect(from.parentElement?.nextElementSibling).toHaveTextContent("Run it");
    expect(screen.getByText("from a pixie")).toBeInTheDocument();
    const report = screen.getByText("Chats finished").parentElement;
    expect(report).toHaveClass("m-sys");
    expect(report).toHaveTextContent("- Check (cv-page): failed");
  });

  it("names the pixie above its message in a chat at rest that can restore files", async () => {
    const api = withChats([session({ id: "s1", title: "Check the form" })], {
      s1: [
        event({ id: 1, type: "session.user_message", payload: { text: "Go", from_pixie: "p1" } }),
      ],
    });
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: /^Check the form,/ }));

    const from = await screen.findByText("from Tester");
    expect(from.parentElement?.nextElementSibling).toHaveClass("m-ur");
  });
});

describe("cards in a pixie's chat (B41)", () => {
  it("shows a started chat's live state and opens it", async () => {
    const started = session({ id: "s1", title: "Check the form", state: "running" });
    const api = withChats([started], { pc: [card(1, "session", "s1")] });
    const { user, push } = await openPixie(api, tester);

    const shown = await screen.findByRole("group", { name: "Chat: Check the form" });
    expect(shown).toHaveTextContent("cv-page");
    expect(shown).toHaveTextContent("Running");
    expect(shown.querySelector(".sp.s-run > .ff")).not.toBeNull();
    push({ id: 9, session_id: "s1", type: "session.state", payload: { state: "failed" } });
    expect(shown).toHaveTextContent("Failed");
    expect(shown.querySelector(".sp.s-fail > .dot")).not.toBeNull();

    await user.click(within(shown).getByRole("button", { name: "Open" }));
    expect(await screen.findByRole("region", { name: "Check the form" })).toBeInTheDocument();
  });

  it("shows a card for a chat no longer listed", async () => {
    const api = withChats([], { pc: [card(1, "session", "gone"), card(2, "pr", "gone")] });
    await openPixie(api, tester);

    expect(await screen.findByRole("group", { name: "Chat: A chat" })).toBeInTheDocument();
    const pr = screen.getByRole("group", { name: "Pull request: A chat" });
    expect(pr).toHaveTextContent("No pull request yet");
    expect(within(pr).queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows a pull request's checks and review, and links to it", async () => {
    const url = "https://github.com/me/cv-page/pull/7";
    const api = withChats(
      [
        session({
          id: "s1",
          title: "Check the form",
          pr_url: url,
          pr: prStatus({ title: "Validate the form", review_decision: "APPROVED" }),
        }),
        session({
          id: "s2",
          title: "Fix the footer",
          pr_url: "https://github.com/me/cv-page/pull/8",
          pr: prStatus({
            number: 8,
            review_decision: "COMMENTED",
            checks: [check("unit", "pending")],
          }),
        }),
        session({ id: "s3", title: "Tidy", pr_url: "https://github.com/me/cv-page/pull/9" }),
      ],
      { pc: [card(1, "pr", "s1"), card(2, "pr", "s2"), card(3, "pr", "s3")] },
    );
    const { user } = await openPixie(api, tester);

    const first = await screen.findByRole("group", { name: "Pull request: Check the form" });
    expect(first).toHaveTextContent("#7 Validate the form");
    expect(first).toHaveTextContent("checks passed, approved");
    expect(within(first).getByRole("link", { name: "GitHub" })).toHaveAttribute("href", url);
    expect(first.querySelector(".pxcm > .dot.s-rev")).not.toBeNull();
    // Checks still running show fireflies (B80).
    const running = screen.getByRole("group", { name: "Pull request: Fix the footer" });
    expect(running).toHaveTextContent("checks running, commented");
    expect(running.querySelector(".pxcm > .ff")).not.toBeNull();
    const unread = screen.getByRole("group", { name: "Pull request: Tidy" });
    expect(unread).toHaveTextContent("#9 Tidy");
    expect(unread).toHaveTextContent("status not read yet");
    expect(within(unread).getByRole("link", { name: "GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/me/cv-page/pull/9",
    );

    await user.click(within(first).getByRole("button", { name: "Open" }));
    expect(await screen.findByRole("region", { name: "Check the form" })).toBeInTheDocument();
  });
});
