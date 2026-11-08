import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { JsonValue, RepoConfig, Session } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { applied, approval, claudeChat, pixie, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";
import { LONG_PRESS_MS } from "./rowGestures.ts";

function withChats(sessions: Session[], repos: (string | RepoConfig)[] = ["todo-ui", "narwhal"]) {
  const api = fakeApi();
  api.repos.mockResolvedValue(repos.map((r) => (typeof r === "string" ? repo(r) : r)));
  api.sessions.mockImplementation((archived) =>
    Promise.resolve(sessions.filter((s) => (s.archived_at !== null) === archived)),
  );
  api.updateSession.mockImplementation((id, body) => {
    const found = defined(sessions.find((s) => s.id === id));
    const archived = body.archived === undefined ? found.archived_at : body.archived ? "x" : null;
    return Promise.resolve({ ...found, ...applied(body), archived_at: archived });
  });
  return api;
}

async function openProjects(sessions: Session[], repos?: (string | RepoConfig)[]) {
  const api = withChats(sessions, repos);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  return rendered;
}

const row = (name: RegExp) => screen.getByRole("button", { name });
const labels = () => screen.queryAllByRole("heading", { level: 2 }).map((h) => h.textContent);
const titles = () =>
  [...document.querySelectorAll<HTMLElement>("#view-projects [data-chat] .rt")].map(
    (t) => t.textContent,
  );
const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

describe("Projects", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("lists every chat by its latest message, whatever it needs (B102 item 9)", async () => {
    const api = withChats([
      session({ id: "w", title: "Waiting one", updated_at: "2026-10-02T00:00:00Z" }),
      session({ id: "r", title: "Busy one", state: "running", updated_at: "2026-10-05T00:00:00Z" }),
      session({ id: "d", title: "Done one", state: "closed", updated_at: "2026-10-06T00:00:00Z" }),
      session({ id: "i", title: "Quiet one", updated_at: "2026-10-01T00:00:00Z" }),
    ]);
    api.approvals.mockResolvedValue([approval({ session_id: "w" })]);
    api.claudeChats.mockResolvedValue([
      claudeChat({ title: "From Claude Code", last_activity_at: "2026-10-04T00:00:00Z" }),
    ]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));

    expect(titles()).toEqual([
      "Done one",
      "Busy one",
      "From Claude Code",
      "Waiting one",
      "Quiet one",
    ]);
    // One list: no Needs you, Running, Idle or Done groups, and no Pinned label unpinned.
    expect(labels()).toEqual(["Chats5"]);
    expect(row(/Waiting one, Needs approval/)).toBeInTheDocument();
  });

  it("lists pinned chats under Pinned above the others, and folds archived ones", async () => {
    const { user } = await openProjects([
      session({ id: "p", title: "Pinned one", pinned: true, updated_at: "2026-10-01T00:00:00Z" }),
      session({ id: "r", title: "Busy one", state: "running" }),
      session({ id: "x", title: "Shelved", archived_at: "2026-10-01T00:00:00Z" }),
    ]);

    expect(labels()).toEqual(["Pinned1", "Chats1"]);
    expect(titles()).toEqual(["Pinned one", "Busy one"]);
    expect(row(/Pinned one, Idle, pinned/)).toBeInTheDocument();
    // A running chat shows fireflies for its dot, an idle one its dot (B80); no glow (B102).
    expect(row(/Busy one, Running/).querySelector(".ff")).not.toBeNull();
    expect(row(/Busy one, Running/).querySelector(".dot")).toBeNull();
    expect(row(/Busy one, Running/)).not.toHaveClass("rglow");
    expect(row(/Pinned one, Idle/).querySelector(".dot")).not.toBeNull();

    const archived = screen.getByRole("button", { name: /Archived/ });
    expect(archived).toHaveTextContent("Archived1");
    expect(archived).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Shelved")).not.toBeInTheDocument();
    await user.click(archived);
    expect(screen.getByText("Shelved")).toBeInTheDocument();
  });

  it("shows the time since each chat's latest message at the row's right (item 2)", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-06T10:00:00Z") });
    await openProjects([
      session({ id: "a", title: "Fresh", updated_at: minutesAgo(4) }),
      session({ id: "b", title: "Older", updated_at: minutesAgo(65), stuck: null }),
    ]);

    const time = (name: RegExp) => row(name).querySelector(".rtime")?.textContent;
    expect(time(/^Fresh,/)).toBe("4m");
    expect(time(/^Older,/)).toBe("1h 5m");
  });

  it("marks a stuck chat with a quiet word, not a tag (item 17)", async () => {
    await openProjects([
      session({
        stuck: { reason: "silent", since: "2026-10-06T09:00:00Z", details: "No new output." },
      }),
    ]);

    const stuck = within(row(/Validate contact form, Idle, stuck/)).getByText("Stuck");
    expect(stuck).toHaveClass("rstuck");
    expect(stuck).toHaveAttribute("title", "No new output.");
  });

  it("names the project, its branch and New chat in a flat header (item 19)", async () => {
    await openProjects([], [{ ...repo("todo-ui"), current_branch: "redesign" }, "narwhal"]);

    const header = screen.getByRole("banner");
    expect(within(header).getByRole("button", { name: "Project: todo-ui" })).toHaveAttribute(
      "aria-haspopup",
      "menu",
    );
    expect(within(header).getByText("redesign")).toBeInTheDocument();
    expect(within(header).getByRole("button", { name: "New chat in todo-ui" })).toBeInTheDocument();
    // No project chips with badges any more.
    expect(screen.queryByRole("tablist", { name: "Projects" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Chats" })).toBeInTheDocument();
  });

  it("shows a project's own sprite as its icon, and no branch for a plain folder", async () => {
    await openProjects(
      [],
      [{ ...repo("todo-ui"), icon: "moth", icon_color: null, git: false, current_branch: null }],
    );

    const header = screen.getByRole("banner");
    expect(within(header).getByRole("img", { name: "moth" })).toBeInTheDocument();
    expect(header.querySelector(".pbr")).toBeNull();
  });

  it("switches projects from the header's menu, Pixies first, as the Mac's tabs", async () => {
    const api = withChats([
      session({ id: "a", repo: "narwhal", title: "Parser" }),
      session({ id: "b", title: "Contact form" }),
    ]);
    api.approvals.mockResolvedValue([approval({ session_id: "b" })]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));

    await user.click(screen.getByRole("button", { name: "Project: todo-ui" }));
    const menu = screen.getByRole("dialog", { name: "Projects" });
    expect(
      within(menu)
        .getAllByRole("menuitemradio")
        .map((i) => i.textContent),
    ).toEqual(["Pixies", "General", "TUtodo-ui", "Nnarwhal"]);
    expect(within(menu).getByRole("menuitemradio", { name: /todo-ui/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await user.click(within(menu).getByRole("menuitemradio", { name: /narwhal/ }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Project: narwhal" })).toBeInTheDocument();
    expect(row(/^Parser, Idle/)).toBeInTheDocument();
    expect(screen.queryByText("Contact form")).not.toBeInTheDocument();
  });

  it("shows the pixies as their own view from the menu, with New pixie in the header", async () => {
    const api = withChats([session()]);
    api.pixies.mockResolvedValue([pixie()]);
    api.createPixie.mockResolvedValue(pixie({ id: "p9", name: "New pixie", slug: "new-pixie" }));
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    expect(screen.queryByRole("button", { name: /^Tester,/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Project: todo-ui" }));
    await user.click(screen.getByRole("menuitemradio", { name: "Pixies" }));

    expect(screen.getByRole("button", { name: "Project: Pixies" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Tester,/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Validate contact form,/ })).toBeNull();
    expect(screen.queryByRole("switch", { name: "Show automated chats" })).toBeNull();
    // No search over chats there, as on the Mac's Pixies tab.
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    await user.click(within(screen.getByRole("banner")).getByRole("button", { name: "New pixie" }));
    expect(api.createPixie).toHaveBeenCalledWith({ name: "New pixie" });
    expect(screen.getByRole("tab", { name: "Details", selected: true })).toBeInTheDocument();
  });

  it("stays on the pixies when creating one from the header fails", async () => {
    const api = withChats([]);
    api.createPixie.mockRejectedValueOnce(new Error("Disk full"));
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: "Project: todo-ui" }));
    await user.click(screen.getByRole("menuitemradio", { name: "Pixies" }));

    await user.click(within(screen.getByRole("banner")).getByRole("button", { name: "New pixie" }));

    expect(await screen.findByText("Disk full")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Project: Pixies" })).toBeInTheDocument();
  });

  // The user removed "Settings for {repo}" (B116 item 5): the project page is under Settings.
  it("ends the projects menu with the projects", async () => {
    const { user } = await openProjects([]);

    await user.click(screen.getByRole("button", { name: "Project: todo-ui" }));

    const menu = screen.getByRole("menu");
    expect([...menu.querySelectorAll("button")].map((b) => b.textContent)).toEqual([
      "Pixies",
      "General",
      "TUtodo-ui",
      "Nnarwhal",
    ]);
  });

  it("closes the menu without switching", async () => {
    const { user } = await openProjects([]);

    await user.click(screen.getByRole("button", { name: "Project: todo-ui" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Project: todo-ui" })).toBeInTheDocument();
  });

  it("follows projects added and removed on the Mac", async () => {
    const { user, push } = await openProjects([session({ id: "a", repo: "narwhal" })]);
    await user.click(screen.getByRole("button", { name: "Project: todo-ui" }));
    await user.click(screen.getByRole("menuitemradio", { name: /narwhal/ }));

    push({
      type: "repo.added",
      payload: { name: "notes", repo: repo("notes") as unknown as JsonValue },
    });
    push({ type: "repo.removed", payload: { name: "narwhal" } });

    // The project on screen went away: the first one shows instead.
    expect(screen.getByRole("button", { name: "Project: todo-ui" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Project: todo-ui" }));
    expect(screen.getAllByRole("menuitemradio").map((i) => i.textContent)).toEqual([
      "Pixies",
      "General",
      "TUtodo-ui",
      "Nnotes",
    ]);
  });

  it("shows empty states", async () => {
    await openProjects([]);
    expect(screen.getByText("No chats yet")).toBeInTheDocument();
    expect(labels()).toEqual([]);
  });

  it("shows General's chats when there is no project yet (B110)", async () => {
    const { user } = await openProjects([session({ id: "g", repo: "general", title: "Disk" })], []);

    expect(screen.getByRole("button", { name: "Project: General" })).toBeInTheDocument();
    expect(row(/^Disk, Idle/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New chat in General" })).toBeInTheDocument();

    // The pixies are still a tap away.
    await user.click(screen.getByRole("button", { name: "Project: General" }));
    expect(screen.getAllByRole("menuitemradio").map((i) => i.textContent)).toEqual([
      "Pixies",
      "General",
    ]);
    await user.click(screen.getByRole("menuitemradio", { name: "Pixies" }));
    expect(screen.getByRole("button", { name: "Project: Pixies" })).toBeInTheDocument();
  });

  it("opens General from the menu: its chats, no branch, no settings (B110)", async () => {
    const api = withChats([
      session({ id: "g", repo: "general", title: "Free disk space" }),
      session({ id: "b", title: "Contact form" }),
    ]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));

    await user.click(screen.getByRole("button", { name: "Project: todo-ui" }));
    const menu = screen.getByRole("dialog", { name: "Projects" });
    expect(within(menu).getByRole("menuitemradio", { name: "General" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    await user.click(within(menu).getByRole("menuitemradio", { name: "General" }));

    const header = screen.getByRole("banner");
    expect(within(header).getByRole("button", { name: "Project: General" })).toBeInTheDocument();
    expect(header.querySelector(".pbr")).toBeNull();
    expect(row(/^Free disk space, Idle/)).toBeInTheDocument();
    expect(screen.queryByText("Contact form")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Project: General" }));
    expect(screen.getByRole("menuitemradio", { name: "General" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.queryByRole("menuitem", { name: /Settings for/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await user.click(screen.getByRole("button", { name: "New chat in General" }));
    expect(screen.getByRole("region", { name: "New chat" })).toBeInTheDocument();
  });

  it("opens a chat with a tap and starts a new one", async () => {
    const { user } = await openProjects([session()]);

    await user.click(row(/Validate contact form, Idle/));
    expect(
      await screen.findByRole("region", { name: "Validate contact form" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to todo-ui" }));
    await user.click(screen.getByRole("button", { name: "New chat in todo-ui" }));

    expect(screen.getByRole("region", { name: "New chat" })).toBeInTheDocument();
  });

  it("returns focus to the chat's row after closing it", async () => {
    const { user } = await openProjects([session()]);
    // A tap on the phone leaves focus where it was; the row gets it back all the same.
    fireEvent.click(row(/Validate contact form, Idle/));
    await screen.findByRole("region", { name: "Validate contact form" });

    await user.click(screen.getByRole("button", { name: "Back to todo-ui" }));

    expect(row(/Validate contact form, Idle/)).toHaveFocus();
  });

  it("returns focus to New chat after leaving a new chat unsent", async () => {
    const { user } = await openProjects([session()]);
    await user.click(screen.getByRole("button", { name: "New chat in todo-ui" }));
    await screen.findByRole("region", { name: "New chat" });

    await user.click(screen.getByRole("button", { name: "Back to todo-ui" }));

    expect(screen.getByRole("button", { name: "New chat in todo-ui" })).toHaveFocus();
  });

  it("folds out a chat's earlier worktrees with a tap that does not open it (B119)", async () => {
    const { user } = await openProjects([
      session({
        id: "moved",
        title: "Moved chat",
        earlier_worktrees: [
          {
            path: "/w/kept",
            branch: "agent/kept",
            base_ref: null,
            started_at: minutesAgo(90),
            ended_at: minutesAgo(30),
            state: "kept",
          },
        ],
      }),
    ]);
    expect(screen.queryByText("kept")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Earlier worktrees of Moved chat" }));

    expect(screen.getByText("kept")).toBeInTheDocument();
    expect(screen.getByTitle("agent/kept")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Chats" })).toHaveAttribute("aria-selected", "true");
    expect(row(/^Moved chat/)).toBeInTheDocument();
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

  it("deletes a chat after confirming that its branch stays (item 30)", async () => {
    const { user, api } = await openProjects([session()]);
    api.deleteSession.mockRejectedValueOnce(new TypeError("offline"));
    const remove = async () => {
      await user.click(screen.getByRole("button", { name: "Actions for Validate contact form" }));
      await user.click(screen.getByRole("menuitem", { name: "Delete" }));
      const confirm = screen.getByRole("alertdialog", { name: "Delete this chat?" });
      expect(confirm).toHaveTextContent(
        "Validate contact form is removed with its worktree and history; its branch stays.",
      );
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
