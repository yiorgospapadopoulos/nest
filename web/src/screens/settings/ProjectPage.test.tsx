import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { Artifact, RepoConfig, Session } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";
import { openSettings } from "../../test/settings.ts";

function withRepos(
  repos: RepoConfig[] = [repo("cv-page"), repo("narrative")],
  sessions: Session[] = [],
  api: FakeApi = fakeApi(),
) {
  api.repos.mockResolvedValue(repos);
  api.sessions.mockImplementation((archived) =>
    Promise.resolve(sessions.filter((s) => (s.archived_at !== null) === archived)),
  );
  // The Mac answers with the project as changed.
  api.updateRepo.mockImplementation((name, patch) => {
    const before = repos.find((r) => r.name === name) ?? repo(name);
    const { link, setup, setup_timeout_seconds, default: mode, ...rest } = patch;
    return Promise.resolve({
      ...before,
      ...rest,
      worktree: {
        ...before.worktree,
        ...(link === undefined ? {} : { link }),
        ...(setup === undefined ? {} : { setup }),
        ...(setup_timeout_seconds === undefined ? {} : { setup_timeout_seconds }),
        ...(mode === undefined ? {} : { default: mode }),
      },
    });
  });
  return api;
}

/** The project's page, reached from its gear on the Projects tab, as before B81. */
async function openFromProjects(...args: Parameters<typeof withRepos>) {
  const api = withRepos(...args);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  await rendered.user.click(screen.getByRole("button", { name: "Settings for cv-page" }));
  await screen.findByRole("heading", { level: 1, name: "cv-page" });
  return rendered;
}

const tab = (name: string) =>
  within(screen.getByRole("group", { name: "Project settings" })).getByRole("button", { name });

const pressed = (group: HTMLElement) =>
  within(group)
    .getAllByRole("button")
    .filter((b) => b.getAttribute("aria-pressed") === "true")
    .map((b) => b.textContent);

describe("project page", () => {
  it("opens from the project's gear and goes back to Projects", async () => {
    const { user } = await openFromProjects();

    expect(screen.getByRole("tab", { name: "Settings" })).toHaveAttribute("aria-selected", "true");
    expect(window.location.pathname).toBe("/settings/projects/cv-page");
    expect(screen.getByText("/Users/me/cv-page")).toBeInTheDocument();
    expect(screen.getByText("Git repository")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to Projects" }));

    expect(screen.getByRole("tab", { name: "Projects" })).toHaveAttribute("aria-selected", "true");
    await user.click(screen.getByRole("tab", { name: "Settings" }));
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  });

  it("leaves the page for the list when another tab is chosen", async () => {
    const { user } = await openFromProjects();

    await user.click(screen.getByRole("tab", { name: "Inbox" }));
    await user.click(screen.getByRole("tab", { name: "Settings" }));

    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  });

  it("opens from the Settings list and goes back to it", async () => {
    const { user } = await openSettings("narrative", { api: withRepos() });

    expect(screen.getByRole("heading", { level: 1, name: "narrative" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to Settings" }));
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    // Tapping the Settings tab again also goes back to the list.
    await user.click(screen.getByRole("button", { name: "narrative" }));
    await user.click(screen.getByRole("tab", { name: "Settings" }));
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  });

  it("opens from its address", async () => {
    window.history.replaceState(null, "", "/settings/projects/narrative");
    await renderApp({ api: withRepos() });

    expect(await screen.findByRole("heading", { level: 1, name: "narrative" })).toBeInTheDocument();
    window.history.replaceState(null, "", "/");
  });

  it("sets the default branch from the local branches", async () => {
    const { user, api } = await openFromProjects();
    const branch = screen.getByLabelText("Default branch");
    await waitFor(() => {
      expect(
        within(branch)
          .getAllByRole("option")
          .map((o) => o.textContent),
      ).toEqual(["develop", "main"]);
    });

    await user.selectOptions(branch, "develop");

    expect(api.updateRepo).toHaveBeenCalledWith("cv-page", { default_branch: "develop" });
    await waitFor(() => {
      expect(screen.getByLabelText("Default branch")).toHaveValue("develop");
    });
  });

  it("keeps the default branch when the Mac refuses it, and copes with none", async () => {
    const api = fakeApi();
    api.updateRepo.mockRejectedValueOnce(new ApiError(422, "no such branch"));
    const { user } = await openFromProjects(
      [{ ...repo("cv-page"), default_branch: null }],
      undefined,
      api,
    );
    const branch = screen.getByLabelText("Default branch");
    await waitFor(() => {
      expect(within(branch).getAllByRole("option")).toHaveLength(3);
    });

    await user.selectOptions(branch, "main");

    expect(await screen.findByText("no such branch")).toBeInTheDocument();
    expect(branch).toHaveValue("");
  });

  it("keeps the default branch listed when the branches cannot load", async () => {
    const api = fakeApi();
    api.branches.mockRejectedValue(new ApiError(409, "not a git repository"));
    await openFromProjects(undefined, undefined, api);

    expect(await screen.findByText("not a git repository")).toBeInTheDocument();
    expect(
      within(screen.getByLabelText("Default branch"))
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["main"]);
  });

  it("changes where the project pushes after a confirmation", async () => {
    const { user, api } = await openFromProjects();
    expect(screen.getByText("git@github.com:me/cv-page.git")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Change" }));
    const field = screen.getByLabelText("Remote address");
    await user.clear(field);
    await user.type(field, "git@github.com:me/other.git");
    await user.click(screen.getByRole("button", { name: "Next" }));
    const confirm = await screen.findByRole("alertdialog", {
      name: "Push cv-page to git@github.com:me/other.git?",
    });
    await user.click(within(confirm).getByRole("button", { name: "Push here" }));

    expect(api.updateRepo).toHaveBeenCalledWith("cv-page", {
      remote_url: "git@github.com:me/other.git",
    });
    expect(await screen.findByText("git@github.com:me/other.git")).toBeInTheDocument();
  });

  it("sets a remote where none is recorded, and can be cancelled", async () => {
    const { user, api } = await openFromProjects([{ ...repo("cv-page"), remote_url: null }]);
    expect(screen.getByText("No remote yet")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Set remote" }));
    await user.click(screen.getByRole("button", { name: "Close" }));
    await user.click(screen.getByRole("button", { name: "Set remote" }));
    await user.type(screen.getByLabelText("Remote address"), "git@x:y.git");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );

    expect(api.updateRepo).not.toHaveBeenCalled();
  });

  it("sets where the project's new chats work", async () => {
    const { user, api } = await openFromProjects();
    await user.click(tab("Chats"));
    const modes = screen.getByRole("group", { name: "Work in" });

    expect(pressed(modes)).toEqual(["New worktree"]);
    await user.click(within(modes).getByRole("button", { name: "Current branch" }));
    await waitFor(() => {
      expect(pressed(modes)).toEqual(["Current branch"]);
    });
    await user.click(within(modes).getByRole("button", { name: "Follow default" }));

    expect(api.updateRepo.mock.calls).toEqual([
      ["cv-page", { default: false }],
      ["cv-page", { default: null }],
    ]);
  });

  it("keeps where chats work when the Mac refuses", async () => {
    const api = withRepos();
    api.updateRepo.mockRejectedValueOnce(new ApiError(500, "Could not write the config"));
    const { user } = await openFromProjects(undefined, undefined, api);
    await user.click(tab("Chats"));

    await user.click(screen.getByRole("button", { name: "Current branch" }));

    expect(await screen.findByText("Could not write the config")).toBeInTheDocument();
    expect(pressed(screen.getByRole("group", { name: "Work in" }))).toEqual(["New worktree"]);
  });

  it("adds and removes linked files and setup commands, and sets the time limit", async () => {
    const configured = {
      ...repo("cv-page"),
      worktree: { default: null, link: [".env"], setup: [], setup_timeout_seconds: 120 },
    };
    const { user, api } = await openFromProjects([configured]);
    await user.click(tab("Worktrees"));

    await user.click(screen.getByRole("button", { name: "Add to Setup commands" }));
    await user.type(screen.getByRole("textbox", { name: "Setup commands" }), "npm ci{Enter}");
    await waitFor(() => {
      expect(api.updateRepo).toHaveBeenCalledWith("cv-page", { setup: ["npm ci"] });
    });
    await user.click(screen.getByRole("button", { name: "Remove .env" }));
    await waitFor(() => {
      expect(api.updateRepo).toHaveBeenCalledWith("cv-page", { link: [] });
    });

    const limit = screen.getByLabelText("Setup time limit");
    expect(
      within(limit)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["2 minutes", "5 minutes", "15 minutes", "30 minutes"]);
    await user.selectOptions(limit, "30");
    expect(api.updateRepo).toHaveBeenCalledWith("cv-page", { setup_timeout_seconds: 1800 });
  });

  it("names a one minute limit in the singular", async () => {
    const configured = {
      ...repo("cv-page"),
      worktree: { default: null, link: [], setup: [], setup_timeout_seconds: 60 },
    };
    const { user } = await openFromProjects([configured]);
    await user.click(tab("Worktrees"));

    expect(screen.getByLabelText("Setup time limit")).toHaveDisplayValue("1 minute");
  });

  it("sets the tab icon and its colour", async () => {
    const { user, api } = await openFromProjects();
    await user.click(tab("Look"));
    expect(screen.queryByRole("group", { name: "Sprite" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Pixie sprite" }));
    expect(api.updateRepo).toHaveBeenLastCalledWith("cv-page", { icon: "invader" });
    const sprites = await screen.findByRole("group", { name: "Sprite" });
    await user.click(within(sprites).getByRole("button", { name: "owl" }));
    expect(api.updateRepo).toHaveBeenLastCalledWith("cv-page", { icon: "owl" });
    await user.click(screen.getByRole("button", { name: "Colour #46A758" }));
    expect(api.updateRepo).toHaveBeenLastCalledWith("cv-page", { icon_color: "#46A758" });
    await user.click(screen.getByRole("button", { name: "Default colour" }));
    expect(api.updateRepo).toHaveBeenLastCalledWith("cv-page", { icon_color: null });
  });

  it("keeps a chosen sprite when switching from initials and back", async () => {
    const styled = { ...repo("cv-page"), icon: "frog" as const, icon_color: "#46A758" };
    const { user, api } = await openFromProjects([styled]);
    await user.click(tab("Look"));

    expect(
      within(screen.getByRole("group", { name: "Sprite" })).getByRole("button", { name: "frog" }),
    ).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Pixie sprite" }));
    expect(api.updateRepo).toHaveBeenLastCalledWith("cv-page", { icon: "frog" });
    await user.click(screen.getByRole("button", { name: "Initials" }));
    expect(api.updateRepo).toHaveBeenLastCalledWith("cv-page", { icon: null });
  });

  it("counts the project's artifacts and has the Artifacts view button", async () => {
    const api = fakeApi();
    api.artifacts.mockResolvedValue([{ id: "a" } as Artifact, { id: "b" } as Artifact]);
    const { user } = await openFromProjects(undefined, undefined, api);
    await user.click(tab("Artifacts"));

    expect(await screen.findByText("2 artifacts")).toBeInTheDocument();
    expect(api.artifacts).toHaveBeenCalledWith({ repo: "cv-page" });
    // The Artifacts view opens on this project, with every project one tap away.
    await user.click(screen.getByRole("button", { name: "Open Artifacts view" }));
    const sheet = await screen.findByRole("dialog", { name: "Artifacts" });
    expect(within(sheet).getByRole("button", { name: "This project" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(sheet).getByRole("button", { name: "All" })).toBeInTheDocument();
    expect(api.artifacts).toHaveBeenLastCalledWith({ repo: "cv-page" });
    await user.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog", { name: "Artifacts" })).not.toBeInTheDocument();
  });

  it.each([
    ["one artifact", () => Promise.resolve([{ id: "a" } as Artifact]), "1 artifact"],
    ["no artifacts", () => Promise.resolve([]), "None yet"],
    [
      "no Artifacts on the Mac yet",
      () => Promise.reject(new ApiError(404, "Not Found")),
      "None yet",
    ],
  ])("says so for %s", async (_, answer, text) => {
    const api = fakeApi();
    api.artifacts.mockImplementation(answer);
    const { user } = await openFromProjects(undefined, undefined, api);
    await user.click(tab("Artifacts"));

    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(screen.queryByText("Not Found")).not.toBeInTheDocument();
  });

  it("ignores a count that arrives after leaving the tab", async () => {
    const api = fakeApi();
    let finish: (value: Artifact[]) => void = () => undefined;
    api.artifacts.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { user } = await openFromProjects(undefined, undefined, api);
    await user.click(tab("Artifacts"));
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    await user.click(tab("General"));

    finish([]);
    await waitFor(() => {
      expect(screen.queryByText("None yet")).not.toBeInTheDocument();
    });
  });

  it("shows only General, Look and Artifacts for a plain folder", async () => {
    const folder = { ...repo("cv-page"), git: false, default_branch: null };
    await openFromProjects([folder]);

    expect(
      within(screen.getByRole("group", { name: "Project settings" }))
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["General", "Look", "Artifacts"]);
    expect(screen.getByText("Plain folder")).toBeInTheDocument();
    expect(screen.queryByLabelText("Default branch")).toBeNull();
  });

  it("remove a project without chats after confirming; its folder stays", async () => {
    const { user, api } = await openFromProjects();
    const remove = () => screen.getByRole("button", { name: "Remove" });

    await user.click(remove());
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(api.removeRepo).not.toHaveBeenCalled();
    await user.click(remove());
    const confirm = await screen.findByRole("alertdialog", { name: "Remove cv-page?" });
    expect(confirm).toHaveTextContent(
      "Nest forgets this project. Its folder stays on your Mac, untouched.",
    );
    await user.click(within(confirm).getByRole("button", { name: "Remove" }));

    expect(api.removeRepo).toHaveBeenCalledWith("cv-page", false);
    expect(await screen.findByText("Removed cv-page")).toBeInTheDocument();
    // Back on Projects, where it was opened from.
    expect(await screen.findByRole("tab", { name: /narrative/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByRole("tab", { name: /cv-page/ })).not.toBeInTheDocument();
  });

  it("say that removing deletes the project's chats, and delete them", async () => {
    const chats = [
      session({ id: "a" }),
      session({ id: "b", archived_at: "2026-10-06T11:00:00Z" }),
      session({ id: "c", repo: "narrative" }),
    ];
    const { user, api } = await openFromProjects(undefined, chats);

    await user.click(screen.getByRole("button", { name: "Remove" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Remove cv-page?" });
    expect(confirm).toHaveTextContent(
      "Its 2 chats are deleted too, with their worktrees and branches.",
    );
    await user.click(within(confirm).getByRole("button", { name: "Remove" }));

    expect(api.removeRepo).toHaveBeenCalledWith("cv-page", true);
    await user.click(await screen.findByRole("tab", { name: /narrative/ }));
    expect(screen.getByRole("button", { name: /^Validate contact form,/ })).toBeInTheDocument();
  });

  it("say one chat in the singular, and keep the project when removing fails", async () => {
    const api = fakeApi();
    api.removeRepo.mockRejectedValueOnce(
      new ApiError(409, "repo 'cv-page' still has 2 session(s)"),
    );
    const { user } = await openFromProjects(undefined, [session()], api);

    await user.click(screen.getByRole("button", { name: "Remove" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Remove cv-page?" });
    expect(confirm).toHaveTextContent("Its chat is deleted too, with its worktree and branch.");
    await user.click(within(confirm).getByRole("button", { name: "Remove" }));

    expect(await screen.findByText("repo 'cv-page' still has 2 session(s)")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "cv-page" })).toBeInTheDocument();
  });

  it("closes when the project is removed on the Mac", async () => {
    const { push } = await openSettings("cv-page", { api: withRepos() });

    push({ type: "repo.removed", payload: { name: "cv-page" } });

    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  });
});
