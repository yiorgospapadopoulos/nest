import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { NestEvent, Session } from "../api/types.ts";
import { fakeApi } from "../test/fakeApi.ts";
import { detail, event, repo, session } from "../test/fixtures.ts";
import { renderApp } from "../test/render.tsx";

const said = (id: number, text: string) =>
  event({ id, type: "session.message", payload: { blocks: [{ type: "text", text }] } });

async function openChat(chat: Session, events: NestEvent[]) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.sessionEvents.mockResolvedValue(events);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  // A daemon restart, or a phone waking up: the socket drops and opens again.
  const reconnect = async () => {
    const count = rendered.sockets.sockets.length;
    act(() => {
      rendered.sockets.last().drop(1006);
    });
    await waitFor(
      () => {
        expect(rendered.sockets.sockets).toHaveLength(count + 1);
      },
      { timeout: 3000 },
    );
    act(() => {
      rendered.sockets.last().open();
    });
  };
  return { ...rendered, reconnect };
}

describe("a reconnect that cannot resume", () => {
  it("fills the gaps in the open chat without duplicates, and drops stale live text", async () => {
    const { api, sockets, push, reconnect } = await openChat(session({ state: "running" }), [
      said(1, "First"),
    ]);
    expect(await screen.findByText("First")).toBeInTheDocument();
    push({ id: null, session_id: "s1", type: "session.delta", payload: { text: "Seco" } });
    expect(screen.getByText("Seco")).toBeInTheDocument();

    // No stored event arrived before the drop, so there is no cursor to resume from, and
    // the daemon replays nothing; meanwhile the turn went on and ended.
    api.sessionEvents.mockResolvedValue([said(1, "First"), said(2, "Second"), said(3, "Third")]);
    api.session.mockResolvedValue(detail(session({ state: "idle" })));
    await reconnect();

    expect(sockets.last().url).toBe("wss://mac.ts.net/api/events");
    // What arrived meanwhile is shown (and, being new, announced too).
    expect(await screen.findByText("Third", { selector: ".tx *" })).toBeInTheDocument();
    expect(screen.getByText("Second", { selector: ".tx *" })).toBeInTheDocument();
    expect(screen.queryByText("Seco")).not.toBeInTheDocument();
    expect(screen.queryByText(/^Working/)).not.toBeInTheDocument();

    // A late live copy of an event the refetch brought is not shown twice.
    push({
      id: 3,
      session_id: "s1",
      type: "session.message",
      payload: { blocks: [{ type: "text", text: "Third" }] },
    });
    expect(screen.getAllByText("Third", { selector: ".tx *" })).toHaveLength(1);
  }, 10_000);

  it("keeps the live text of a turn that is still running", async () => {
    const { api, push, reconnect } = await openChat(session({ state: "running" }), [
      said(1, "First"),
    ]);
    await screen.findByText("First");
    push({ id: null, session_id: "s1", type: "session.delta", payload: { text: "Seco" } });

    api.sessionEvents.mockResolvedValue([said(1, "First"), said(2, "Second")]);
    await reconnect();

    expect(await screen.findByText("Second", { selector: ".tx *" })).toBeInTheDocument();
    expect(screen.getByText("Seco")).toBeInTheDocument();
  }, 10_000);

  it("refetches only the chats still on screen", async () => {
    const { api, user, reconnect } = await openChat(session(), [said(1, "First")]);
    await screen.findByText("First");
    await user.click(screen.getByRole("button", { name: /back/i }));
    const calls = api.sessionEvents.mock.calls.length;

    await reconnect();

    await waitFor(() => {
      expect(api.repos).toHaveBeenCalledTimes(2);
    });
    expect(api.sessionEvents).toHaveBeenCalledTimes(calls);
  }, 10_000);
});

describe("a chat whose history failed to load", () => {
  it("says so, and loads it again after a resumed reconnect", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("cv-page")]);
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [session()]));
    api.sessionEvents.mockRejectedValueOnce(new Error("Request failed (502)"));
    api.sessionEvents.mockResolvedValue([said(1, "First")]);
    const { user, sockets, push } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));

    expect(await screen.findByText("The messages could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText("No messages yet")).not.toBeInTheDocument();
    // A stored event gives the socket a cursor, so the reconnect resumes from it.
    push({ id: 3, session_id: "s2", type: "session.state", payload: { state: "idle" } });
    const count = sockets.sockets.length;
    act(() => {
      sockets.last().drop(1006);
    });
    await waitFor(
      () => {
        expect(sockets.sockets).toHaveLength(count + 1);
      },
      { timeout: 3000 },
    );
    act(() => {
      sockets.last().open();
    });

    expect(sockets.last().url).toBe("wss://mac.ts.net/api/events?after=3");
    expect(await screen.findByText("First", { selector: ".tx *" })).toBeInTheDocument();
    expect(screen.queryByText("The messages could not be loaded.")).not.toBeInTheDocument();
    expect(api.repos).toHaveBeenCalledTimes(1);
  }, 10_000);

  it("loads it again from Retry", async () => {
    const api = fakeApi();
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [session()]));
    api.sessionEvents.mockRejectedValueOnce(new Error("Request failed (502)"));
    api.sessionEvents.mockResolvedValue([said(1, "First")]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));

    await user.click(await screen.findByRole("button", { name: "Retry" }));

    expect(await screen.findByText("First", { selector: ".tx *" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });
});
