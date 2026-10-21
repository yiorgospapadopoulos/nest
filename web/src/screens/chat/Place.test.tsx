/// <reference types="node" />
import { readFileSync } from "node:fs";
import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ClaudeChat, RepoConfig, Session } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { defined } from "../../test/defined.ts";
import { NOW, agentDefaults, claudeChat, detail, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";
import { claudeChatPlace, sessionPlace } from "./place.ts";

const inPlace = (overrides: Partial<Session> = {}) =>
  session({
    id: "s2",
    title: "Tidy styles",
    mode: "in_place",
    cwd: "/Users/me/cv-page",
    worktree_path: null,
    branch: null,
    ...overrides,
  });

async function projects(
  sessions: Session[],
  chats: ClaudeChat[] = [],
  repos: RepoConfig[] = [repo("cv-page")],
) {
  const api = fakeApi();
  api.repos.mockResolvedValue(repos);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : sessions));
  api.claudeChats.mockResolvedValue(chats);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  return rendered;
}

const row = (name: RegExp) => screen.getByRole("button", { name });

describe("where a chat works, in the list", () => {
  it("marks an in-place chat with the folder's branch and a worktree chat with its name", async () => {
    await projects([session(), inPlace()]);

    const worktree = row(/^Validate contact form,/);
    expect(worktree).toHaveAccessibleName("Validate contact form, Idle, worktree agent/contact");
    expect(within(worktree).getByText("agent/contact")).toBeInTheDocument();
    const checkout = row(/^Tidy styles,/);
    expect(checkout).toHaveAccessibleName("Tidy styles, Idle, on main");
    expect(within(checkout).getByText("main")).toBeInTheDocument();
    expect(worktree.querySelectorAll(".plm svg")).toHaveLength(1);
    expect(checkout.querySelectorAll(".plm svg")).toHaveLength(1);
  });

  it("puts the mark beneath the whole title, with the time at the row's end", async () => {
    const sheet = document.createElement("style");
    sheet.textContent = readFileSync("src/styles/screens.css", "utf8");
    document.head.append(sheet);
    const long = "Make the contact form validate every field and explain each error clearly";
    await projects(
      [
        inPlace({
          title: long,
          pinned: true,
          stuck: { reason: "silent", since: NOW, details: "No new output." },
        }),
      ],
      [claudeChat({ worktree: "agent-x" })],
    );

    for (const [found, mark] of [
      [row(/^Make the contact form/), "main"],
      [row(/^Tune the hero section,/), "agent-x"],
    ] as const) {
      const title = defined(found.querySelector<HTMLElement>(".rt"));
      const below = defined(title.nextElementSibling);
      expect(below).toHaveClass("rsub");
      expect(title.querySelector(".plm")).toBeNull();
      expect(
        within(below as HTMLElement)
          .getByText(mark)
          .closest(".plm"),
      ).not.toBeNull();
      // The time of the last message ends the row, beside the title (B102 item 2).
      expect(found.lastElementChild).toHaveClass("rtime");
      const style = getComputedStyle(title);
      expect(style.whiteSpace).toBe("normal");
      expect(style.textOverflow).not.toBe("ellipsis");
    }
    expect(row(/^Make the contact form/).querySelector(".rt")).toHaveTextContent(long);
    sheet.remove();
  });

  it("says this folder for an in-place chat when the branch is unknown", async () => {
    const detached = { ...repo("cv-page"), current_branch: null };
    await projects([inPlace()], [], [detached]);

    const checkout = row(/^Tidy styles,/);
    expect(checkout).toHaveAccessibleName("Tidy styles, Idle, in this folder");
    expect(within(checkout).getByText("This folder")).toBeInTheDocument();
  });

  it("says New worktree while a worktree chat's worktree is being made", async () => {
    await projects([session({ worktree_path: null, branch: null, cwd: null })]);

    expect(row(/^Validate contact form,/)).toHaveAccessibleName(
      "Validate contact form, Idle, worktree New worktree",
    );
  });

  it("marks a Claude Code chat by its worktree or the folder's branch", async () => {
    await projects(
      [],
      [claudeChat(), claudeChat({ id: "c2", title: "Try a layout", worktree: "agent-x" })],
    );

    const plain = row(/^Tune the hero section,/);
    const worktree = row(/^Try a layout,/);
    expect(screen.queryByText("Claude Code")).not.toBeInTheDocument();
    expect(plain).toHaveAccessibleName("Tune the hero section, Claude Code chat, on main");
    expect(within(plain).getByText("main")).toBeInTheDocument();
    expect(worktree).toHaveAccessibleName("Try a layout, Claude Code chat, worktree agent-x");
    expect(within(worktree).getByText("agent-x")).toBeInTheDocument();
  });

  it("marks nothing in a plain folder", async () => {
    const notes: RepoConfig = {
      ...repo("cv-page"),
      git: false,
      default_branch: null,
      current_branch: null,
    };
    await projects([inPlace()], [claudeChat()], [notes]);

    expect(row(/^Tidy styles,/)).toHaveAccessibleName("Tidy styles, Idle");
    expect(row(/^Tidy styles,/).querySelector(".plm")).toBeNull();
    expect(row(/^Tune the hero section,/)).toHaveAccessibleName(
      "Tune the hero section, Claude Code chat",
    );
  });
});

async function openChat(chat: Session, repos: RepoConfig[] = [repo("cv-page")]) {
  const rendered = await projects([chat], [], repos);
  rendered.api.session.mockResolvedValue(detail(chat));
  await rendered.user.click(row(new RegExp(`^${chat.title},`)));
  return within(await screen.findByRole("region", { name: chat.title }));
}

describe("where a chat works, in its header", () => {
  it("names a worktree chat's worktree", async () => {
    const view = await openChat(session());

    const place = view.getByTitle("Worktree agent/contact in /w/s1");
    expect(place).toHaveTextContent("Worktree agent/contact");
    expect(place.querySelector(".sr")).toHaveTextContent("Worktree");
    expect(place.querySelectorAll("svg")).toHaveLength(1);
  });

  it("says New worktree while the worktree is being made", async () => {
    const view = await openChat(session({ worktree_path: null, branch: null, cwd: null }));

    expect(view.getByTitle("Worktree New worktree")).toHaveTextContent("New worktree");
  });

  it("names the folder's branch for an in-place chat, with the folder", async () => {
    const view = await openChat(inPlace());

    const place = view.getByTitle("On main in /Users/me/cv-page");
    expect(place).toHaveTextContent(/^On main$/);
    expect(place.querySelector(".sr")).toHaveTextContent("On");
  });

  it("names the project folder for an in-place chat without its own", async () => {
    const view = await openChat(inPlace({ cwd: null }));

    expect(view.getByTitle("On main in /Users/me/cv-page")).toBeVisible();
  });

  it("says This folder for an in-place chat when the branch is unknown", async () => {
    const detached: RepoConfig = { ...repo("cv-page"), current_branch: null };
    const view = await openChat(inPlace(), [detached]);

    expect(view.getByTitle("In /Users/me/cv-page")).toHaveTextContent(/^This folder$/);
  });

  it("says nothing in a plain folder", async () => {
    const plain: RepoConfig = { ...repo("cv-page"), git: false, current_branch: null };
    const view = await openChat(inPlace(), [plain]);

    expect(view.queryByTitle(/cv-page/)).not.toBeInTheDocument();
    expect(view.queryByText("This folder")).not.toBeInTheDocument();
  });

  it("knows no place for an in-place chat without a folder or a project", () => {
    expect(sessionPlace(inPlace({ cwd: null }), undefined)).toBeNull();
  });

  it("names a Claude Code chat's worktree, or the folder's branch", async () => {
    const { user } = await projects(
      [],
      [claudeChat(), claudeChat({ id: "c2", title: "Try a layout", worktree: "agent-x" })],
    );

    await user.click(row(/^Try a layout,/));
    const worktree = within(await screen.findByRole("region", { name: "Try a layout" }));
    expect(worktree.getByTitle("Worktree agent-x in /Users/me/cv-page")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Back to cv-page" }));
    await user.click(row(/^Tune the hero section,/));
    const checkout = within(await screen.findByRole("region", { name: "Tune the hero section" }));
    expect(checkout.getByTitle("On main in /Users/me/cv-page")).toHaveTextContent("On main");
  });

  it("says This folder for a Claude Code chat outside a known project", () => {
    expect(claudeChatPlace(claudeChat(), undefined)).toEqual({
      kind: "checkout",
      folder: "/Users/me/cv-page",
      branch: null,
    });
  });
});

async function newChat(api: FakeApi = fakeApi(), repos: RepoConfig[] = [repo("cv-page")]) {
  api.repos.mockResolvedValue(repos);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: "New chat in cv-page" }));
  await waitFor(() => {
    expect(api.agentDefaults).toHaveBeenCalled();
  });
  return rendered;
}

// What a new chat sends from the agent defaults, which name no model (B102).
const CHOICES = { provider: "claude", effort: "medium", permission_mode: "default" };

const placeButton = () => screen.getByRole("button", { name: /^Where the chat works: / });

async function choose(user: Awaited<ReturnType<typeof newChat>>["user"], option: string) {
  await user.click(placeButton());
  const sheet = screen.getByRole("dialog", { name: "Where the chat works" });
  await user.click(
    await within(sheet).findByRole("menuitemradio", { name: new RegExp(`^${option}`) }),
  );
}

describe("where a new chat works", () => {
  it("offers the folder's branch first, then a new worktree, each with its detail", async () => {
    const { user } = await newChat();

    const button = placeButton();
    expect(button).toHaveAccessibleName("Where the chat works: New worktree");
    expect(button).toHaveAttribute("aria-haspopup", "dialog");
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const sheet = screen.getByRole("dialog", { name: "Where the chat works" });
    const options = within(sheet).getAllByRole("menuitemradio");
    expect(options.map((o) => o.textContent)).toEqual([
      "Work on mainEdits the project folder, on main",
      "New worktreeA separate copy of the project on its own new branch",
    ]);
    expect(options.map((o) => o.getAttribute("aria-checked"))).toEqual(["false", "true"]);
  });

  it("starts a new worktree from the folder's current branch under the typed name", async () => {
    const api = fakeApi();
    api.repo.mockResolvedValue({ ...repo("cv-page"), current_branch: "dev" });
    const { user } = await newChat(api);

    expect(placeButton()).toHaveAccessibleName("Where the chat works: New worktree");
    await waitFor(() => {
      expect(api.repo).toHaveBeenCalledWith("cv-page");
    });
    expect(screen.queryByLabelText("From")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Branch name"), "  try/layout ");
    await user.type(screen.getByLabelText("Message"), "Go{Enter}");

    expect(api.createSession).toHaveBeenCalledWith({
      repo: "cv-page",
      prompt: "Go",
      attachment_ids: [],
      ...CHOICES,
      mode: "worktree",
      base: "dev",
      branch: "try/layout",
    });
    // Once sent, the chat's place is its header's label and no longer a choice.
    expect(await screen.findByRole("region", { name: "Validate contact form" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /^Where the chat works/ })).toBeNull();
  });

  it("works on the folder's branch, read fresh, without a branch name", async () => {
    const api = fakeApi();
    api.repo.mockResolvedValue({ ...repo("cv-page"), current_branch: "dev" });
    const { user } = await newChat(api);

    await choose(user, "Work on dev");

    expect(placeButton()).toHaveAccessibleName("Where the chat works: Work on dev");
    expect(screen.queryByLabelText("Branch name")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Message"), "Go{Enter}");
    expect(api.createSession).toHaveBeenCalledWith({
      repo: "cv-page",
      prompt: "Go",
      attachment_ids: [],
      ...CHOICES,
      mode: "in_place",
    });
  });

  it("follows the agent default when the project has none", async () => {
    const api = fakeApi();
    api.agentDefaults.mockResolvedValue(agentDefaults({ mode: "worktree" }));
    const own = { ...repo("cv-page"), worktree: { ...repo("cv-page").worktree, default: null } };
    await newChat(api, [own]);

    await waitFor(() => {
      expect(placeButton()).toHaveAccessibleName("Where the chat works: New worktree");
    });
  });

  it("works on the current branch by default when the project says so", async () => {
    const own = { ...repo("cv-page"), worktree: { ...repo("cv-page").worktree, default: false } };
    await newChat(fakeApi(), [own]);

    expect(placeButton()).toHaveAccessibleName("Where the chat works: Work on main");
    expect(screen.queryByLabelText("Branch name")).not.toBeInTheDocument();
  });

  it("works in place by default when nothing is known", async () => {
    const api = fakeApi();
    api.agentDefaults.mockRejectedValue(new Error("offline"));
    const own = { ...repo("cv-page"), worktree: { ...repo("cv-page").worktree, default: null } };
    await newChat(api, [own]);

    expect(placeButton()).toHaveAccessibleName("Where the chat works: Work on main");
  });

  it("says this folder on a detached checkout and sends no base, nor a blank name", async () => {
    const api = fakeApi();
    const detached = { ...repo("cv-page"), current_branch: null };
    api.repo.mockRejectedValue(new Error("offline"));
    const { user } = await newChat(api, [detached]);

    await user.type(screen.getByLabelText("Branch name"), "   ");
    await user.click(placeButton());
    const sheet = screen.getByRole("dialog", { name: "Where the chat works" });
    expect(within(sheet).getAllByRole("menuitemradio")[0]).toHaveTextContent(
      "Work in this folderEdits the project folder",
    );
    await user.click(within(sheet).getByRole("menuitemradio", { name: /^Work in this folder/ }));
    expect(placeButton()).toHaveAccessibleName("Where the chat works: Work in this folder");
    await choose(user, "New worktree");
    await user.type(screen.getByLabelText("Message"), "Go{Enter}");

    expect(api.createSession).toHaveBeenCalledWith({
      repo: "cv-page",
      prompt: "Go",
      attachment_ids: [],
      ...CHOICES,
      mode: "worktree",
    });
  });

  it("offers no choice in a plain folder", async () => {
    const api = fakeApi();
    const plain: RepoConfig = {
      ...repo("cv-page"),
      git: false,
      default_branch: null,
      current_branch: null,
    };
    const { user } = await newChat(api, [plain]);

    expect(screen.queryByRole("button", { name: /^Where the chat works/ })).toBeNull();
    expect(screen.queryByLabelText("Branch name")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Message"), "Go{Enter}");
    expect(api.createSession).toHaveBeenCalledWith({
      repo: "cv-page",
      prompt: "Go",
      attachment_ids: [],
      ...CHOICES,
    });
    expect(api.repo).not.toHaveBeenCalled();
  });
});
