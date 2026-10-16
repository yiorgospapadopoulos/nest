import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { JsonValue, Session } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { approval, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";
import { LONG_PRESS_MS } from "./rowGestures.ts";

function withChats(sessions: Session[], repos = ["cv-page", "narrative"]) {
  const api = fakeApi();
  api.repos.mockResolvedValue(repos.map(repo));
  api.sessions.mockImplementation((archived) =>
    Promise.resolve(sessions.filter((s) => (s.archived_at !== null) === archived)),
  );
  api.updateSession.mockImplementation((id, body) => {
    const found = defined(sessions.find((s) => s.id === id));
    const archived = body.archived === undefined ? found.archived_at : body.archived ? "x" : null;
    return Promise.resolve({ ...found, ...body, archived_at: archived });
  });
  return api;
}

async function openProjects(sessions: Session[], repos?: string[]) {
  const api = withChats(sessions, repos);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  return rendered;
}

const row = (name: RegExp) => screen.getByRole("button", { name });

describe("Projects", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("lists project chips with attention, counts and running dots", async () => {
    const api = withChats([
      session({ id: "a", repo: "narrative", state: "running" }),
      session({ id: "b", repo: "cv-page" }),
    ]);
    api.approvals.mockResolvedValue([approval({ session_id: "b" })]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));

    const cv = screen.getByRole("tab", { name: /cv-page/ });
    const narrative = screen.getByRole("tab", { name: /narrative/ });
    expect(cv).toHaveAttribute("aria-selected", "true");
    expect(within(cv).getByLabelText("1 need you")).toBeInTheDocument();
    expect(within(narrative).getByLabelText("running")).toBeInTheDocument();
    await user.click(narrative);
    expect(narrative).toHaveAttribute("aria-selected", "true");
    expect(cv).toHaveClass("attn");
    expect(row(/Validate contact form, Running/)).toBeInTheDocument();
  });

  it("follows projects added and removed on the Mac", async () => {
    const { user, push } = await openProjects([session({ id: "a", repo: "narrative" })]);
    await user.click(screen.getByRole("tab", { name: /narrative/ }));

    push({
      type: "repo.added",
      payload: { name: "notes", repo: repo("notes") as unknown as JsonValue },
    });
    expect(screen.getByRole("tab", { name: /notes/ })).toBeInTheDocument();
    push({ type: "repo.removed", payload: { name: "narrative" } });

    expect(screen.queryByRole("tab", { name: /narrative/ })).not.toBeInTheDocument();
    // The project on screen went away: the first one shows instead.
    expect(screen.getByRole("tab", { name: /cv-page/ })).toHaveAttribute("aria-selected", "true");
  });

  it("groups chats and folds archived ones", async () => {
    const { user } = await openProjects([
      session({ id: "p", title: "Pinned one", pinned: true }),
      session({ id: "r", title: "Busy one", state: "running" }),
      session({ id: "d", title: "Old one", state: "closed" }),
      session({ id: "x", title: "Shelved", archived_at: "2026-10-01T00:00:00Z" }),
    ]);

    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Pixies0",
      "Goals",
      "Pinned1",
      "Running1",
      "Done1",
    ]);
    expect(row(/Pinned one, Idle, pinned/)).toBeInTheDocument();
    expect(screen.queryByText("Shelved")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Archived/ }));
    expect(screen.getByText("Shelved")).toBeInTheDocument();
  });

  it("shows empty states", async () => {
    await openProjects([]);
    expect(screen.getByText("No chats yet")).toBeInTheDocument();
  });

  it("explains how to add the first project", async () => {
    await openProjects([], []);
    expect(screen.getByText(/No projects yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /New chat/ })).not.toBeInTheDocument();
  });

  it("opens a chat with a tap and starts a new one", async () => {
    const { user } = await openProjects([session()]);

    await user.click(row(/Validate contact form, Idle/));
    expect(
      await screen.findByRole("region", { name: "Validate contact form" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to cv-page" }));
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));

    expect(screen.getByRole("region", { name: "New chat" })).toBeInTheDocument();
  });

  it("returns focus to the chat's row after closing it", async () => {
    const { user } = await openProjects([session()]);
    // A tap on the phone leaves focus where it was; the row gets it back all the same.
    fireEvent.click(row(/Validate contact form, Idle/));
    await screen.findByRole("region", { name: "Validate contact form" });

    await user.click(screen.getByRole("button", { name: "Back to cv-page" }));

    expect(row(/Validate contact form, Idle/)).toHaveFocus();
  });

  it("returns focus to New chat after leaving a new chat unsent", async () => {
    const { user } = await openProjects([session()]);
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));
    await screen.findByRole("region", { name: "New chat" });

    await user.click(screen.getByRole("button", { name: "Back to cv-page" }));

    expect(screen.getByRole("button", { name: "New chat in cv-page" })).toHaveFocus();
  });

  it("opens actions with long-press, swipe, context menu and the dots button", async () => {
    const { user, api } = await openProjects([session()]);
    const target = row(/Validate contact form, Idle/);
    const close = async () => {
      await user.click(await screen.findByRole("button", { name: "Cancel" }));
    };

    vi.useFakeTimers();
    fireEvent.pointerDown(target, { button: 0, clientX: 100, clientY: 10 });
    fireEvent.pointerMove(target, { clientX: 103, clientY: 12 });
    act(() => {
      vi.advanceTimersByTime(LONG_PRESS_MS);
    });
    fireEvent.pointerUp(target);
    fireEvent.click(target);
    vi.useRealTimers();
    expect(
      screen.getByRole("dialog", { name: "Actions for Validate contact form" }),
    ).toBeInTheDocument();
    await close();

    fireEvent.pointerDown(target, { button: 0, clientX: 100, clientY: 10 });
    fireEvent.pointerMove(target, { clientX: 30, clientY: 12 });
    fireEvent.pointerMove(target, { clientX: 20, clientY: 12 });
    fireEvent.pointerUp(target);
    fireEvent.click(target);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    await close();

    fireEvent.contextMenu(target);
    await close();
    await user.click(screen.getByRole("button", { name: "Actions for Validate contact form" }));
    await close();

    fireEvent.pointerDown(target, { button: 2 });
    fireEvent.pointerMove(target, { clientX: 0 });
    fireEvent.pointerDown(target, { button: 0, clientX: 100, clientY: 10 });
    fireEvent.pointerMove(target, { clientX: 100, clientY: 40 });
    fireEvent.pointerCancel(target);
    fireEvent.pointerUp(target);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.session).not.toHaveBeenCalled();
  });

  it("pins, unpins, archives and unarchives", async () => {
    const { user, api } = await openProjects([
      session(),
      session({ id: "s2", title: "Pinned", pinned: true }),
      session({ id: "s3", title: "Shelved", archived_at: "x" }),
    ]);
    const act = async (chat: string, item: string) => {
      await user.click(screen.getByRole("button", { name: `Actions for ${chat}` }));
      await user.click(screen.getByRole("menuitem", { name: item }));
    };

    await act("Validate contact form", "Pin");
    expect(await screen.findByText("Pinned Validate contact form")).toBeInTheDocument();
    await act("Pinned", "Unpin");
    await act("Validate contact form", "Archive");
    await user.click(screen.getByRole("button", { name: /Archived/ }));
    await act("Shelved", "Unarchive");

    expect(api.updateSession.mock.calls).toEqual([
      ["s1", { pinned: true }],
      ["s2", { pinned: false }],
      ["s1", { archived: true }],
      ["s3", { archived: false }],
    ]);
    expect(await screen.findByText("Unarchived Shelved")).toBeInTheDocument();
  });

  it("keeps the actions open when a change fails", async () => {
    const { user, api } = await openProjects([session()]);
    api.updateSession.mockRejectedValueOnce(new ApiError(404, "unknown session"));

    await user.click(screen.getByRole("button", { name: "Actions for Validate contact form" }));
    await user.click(screen.getByRole("menuitem", { name: "Pin" }));

    expect(await screen.findByText("unknown session")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("renames a chat", async () => {
    const { user, api } = await openProjects([session()]);
    const rename = async () => {
      await user.click(screen.getByRole("button", { name: "Actions for Validate contact form" }));
      await user.click(screen.getByRole("menuitem", { name: "Rename" }));
      return screen.getByLabelText("Chat title");
    };

    let field = await rename();
    expect(field).toHaveFocus();
    expect((field as HTMLInputElement).selectionEnd).toBe("Validate contact form".length);
    await user.clear(field);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Type a title")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    field = await rename();
    await user.clear(field);
    await user.type(field, "Zod validation{Enter}");

    expect(api.updateSession).toHaveBeenCalledWith("s1", { title: "Zod validation" });
    expect(await screen.findByText("Renamed to Zod validation")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("deletes a chat after confirming", async () => {
    const { user, api } = await openProjects([session()]);
    api.deleteSession.mockRejectedValueOnce(new TypeError("offline"));
    const remove = async () => {
      await user.click(screen.getByRole("button", { name: "Actions for Validate contact form" }));
      await user.click(screen.getByRole("menuitem", { name: "Delete" }));
      const confirm = screen.getByRole("alertdialog", { name: "Delete this chat?" });
      await user.click(within(confirm).getByRole("button", { name: "Delete chat" }));
    };

    await remove();
    expect(await screen.findByText("offline")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await remove();

    expect(api.deleteSession).toHaveBeenCalledWith("s1");
    await waitFor(() => {
      expect(screen.getByText("No chats yet")).toBeInTheDocument();
    });
    expect(screen.getByText("Deleted Validate contact form")).toBeInTheDocument();
  });
});
