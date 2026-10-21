import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { Artifact, RepoConfig, Session } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { projectConfiguration, repo, session, skillItem } from "../../test/fixtures.ts";
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

/**
 * The project's page, reached from the Settings list. Opening it from the Chats tab's
 * project menu, and going back there, belongs to that tab's tests (B102 stage 2, Lists).
 */
async function openFromProjects(...args: Parameters<typeof withRepos>) {
  const api = withRepos(...args);
  const rendered = await openSettings("cv-page", { api });
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
  it("shows the project's folder and kind, in the address", async () => {
    await openFromProjects();

    expect(screen.getByRole("tab", { name: "Settings" })).toHaveAttribute("aria-selected", "true");
    expect(window.location.pathname).toBe("/settings/projects/cv-page");
    expect(screen.getByText("/Users/me/cv-page")).toBeInTheDocument();
    expect(screen.getByText("Git repository")).toBeInTheDocument();
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
    // One already there is not added again.
    await user.click(screen.getByRole("button", { name: "Add to Linked files" }));
    await user.type(screen.getByRole("textbox", { name: "Linked files" }), ".env{Enter}");
    expect(api.updateRepo).not.toHaveBeenCalledWith("cv-page", { link: [".env", ".env"] });
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
    expect(api.updateRepo).toHaveBeenLastCalledWith("cv-page", { icon: "bluebell" });
    const sprites = await screen.findByRole("group", { name: "Sprite" });
    await user.click(within(sprites).getByRole("button", { name: "moth" }));
    expect(api.updateRepo).toHaveBeenLastCalledWith("cv-page", { icon: "moth" });
    await user.click(screen.getByRole("button", { name: "Colour #46A758" }));
    expect(api.updateRepo).toHaveBeenLastCalledWith("cv-page", { icon_color: "#46A758" });
    await user.click(screen.getByRole("button", { name: "Default colour" }));
    expect(api.updateRepo).toHaveBeenLastCalledWith("cv-page", { icon_color: null });
  });

  it("keeps a chosen sprite when switching from initials and back", async () => {
    const styled = { ...repo("cv-page"), icon: "dragonfly" as const, icon_color: "#46A758" };
    const { user, api } = await openFromProjects([styled]);
    await user.click(tab("Look"));

    expect(
      within(screen.getByRole("group", { name: "Sprite" })).getByRole("button", {
        name: "dragonfly",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Pixie sprite" }));
    expect(api.updateRepo).toHaveBeenLastCalledWith("cv-page", { icon: "dragonfly" });
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
    ).toEqual(["General", "Configuration", "Look", "Artifacts"]);
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
    expect(confirm).toHaveTextContent("Nest forgets this project. Its folder stays as it is.");
    expect(confirm).not.toHaveTextContent("deleted");
    await user.click(within(confirm).getByRole("button", { name: "Remove" }));

    expect(api.removeRepo).toHaveBeenCalledWith("cv-page", false);
    expect(await screen.findByText("Removed cv-page")).toBeInTheDocument();
    // Back on the list, where it was opened from.
    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "cv-page" })).not.toBeInTheDocument();
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
    // B96: the branches stay; only the worktrees go (B102 item 30).
    expect(confirm).toHaveTextContent(
      "Its 2 chats are deleted for good, with their worktrees and history; their branches stay.",
    );
    await user.click(within(confirm).getByRole("button", { name: "Remove" }));

    expect(api.removeRepo).toHaveBeenCalledWith("cv-page", true);
    expect(await screen.findByText("Removed cv-page")).toBeInTheDocument();
  });

  it("say one chat in the singular, and keep the project when removing fails", async () => {
    const api = fakeApi();
    api.removeRepo.mockRejectedValueOnce(
      new ApiError(409, "repo 'cv-page' still has 2 session(s)"),
    );
    const { user } = await openFromProjects(undefined, [session()], api);

    await user.click(screen.getByRole("button", { name: "Remove" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Remove cv-page?" });
    expect(confirm).toHaveTextContent(
      "Its chat is deleted for good, with its worktree and history; its branch stays.",
    );
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

describe("project configuration", () => {
  async function openConfiguration(api = fakeApi()) {
    const rendered = await openSettings("cv-page", { api: withRepos(undefined, [], api) });
    await rendered.user.click(tab("Configuration"));
    return rendered;
  }

  it("shows the project's instructions, skills and MCP servers, Claude only", async () => {
    const api = fakeApi();
    api.projectConfiguration.mockResolvedValue(
      projectConfiguration({
        instructions: [
          { path: "/Users/me/cv-page/AGENTS.md", exists: false },
          { path: "/Users/me/cv-page/CLAUDE.md", exists: true },
          { path: "/Users/me/cv-page/docs/AGENTS.md", exists: true },
        ],
        skills: [
          skillItem({
            name: "publish-cv",
            description: "Builds the PDF",
            source: "project",
            path: "/Users/me/cv-page/.claude/skills/publish-cv/SKILL.md",
          }),
          skillItem({ name: "bare", description: null, source: "project" }),
        ],
        mcp_servers: [{ name: "lighthouse", summary: "npx lighthouse-mcp", transport: "stdio" }],
      }),
    );
    const { user } = await openConfiguration(api);

    expect(screen.getByText(/This project's own instructions/)).toBeInTheDocument();
    expect(api.projectConfiguration).toHaveBeenCalledWith("cv-page");
    const instructions = await screen.findByRole("region", { name: "Instructions" });
    expect(within(instructions).getByText("Not made yet")).toBeInTheDocument();
    expect(within(instructions).getByText("Read by Claude")).toBeInTheDocument();
    expect(
      within(instructions).getByText("Read by Codex; Claude reads it when CLAUDE.md imports it"),
    ).toBeInTheDocument();
    expect(within(instructions).getByRole("button", { name: "Create AGENTS.md" })).toBeVisible();
    const skills = screen.getByRole("region", { name: "Skills" });
    expect(within(skills).getByText(".claude/skills · Claude only")).toBeInTheDocument();
    expect(within(skills).getByText("Builds the PDF")).toBeInTheDocument();
    const servers = screen.getByRole("region", { name: "MCP servers" });
    expect(within(servers).getByText(".mcp.json · Claude only")).toBeInTheDocument();
    expect(within(servers).getByText("npx lighthouse-mcp")).toBeInTheDocument();
    expect(screen.queryByText(/Open in VS Code|Open folder/)).toBeNull();

    await user.click(within(instructions).getByRole("button", { name: "Edit CLAUDE.md" }));
    const editor = await screen.findByRole("dialog", { name: "CLAUDE.md" });
    expect(editor).toHaveTextContent("~/cv-page/CLAUDE.md · cv-page");
    await user.click(within(editor).getByRole("button", { name: "Cancel" }));

    await user.click(within(skills).getByRole("button", { name: "Edit publish-cv" }));
    expect(await screen.findByRole("dialog", { name: "publish-cv" })).toHaveTextContent(
      "project skill",
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await user.click(within(servers).getByRole("button", { name: "Edit .mcp.json" }));
    expect(await screen.findByRole("dialog", { name: "MCP servers" })).toHaveTextContent(
      "~/cv-page/.mcp.json · cv-page",
    );
  });

  it("waits for the project's part, and follows changes on disk", async () => {
    const api = fakeApi();
    let first: (value: ReturnType<typeof projectConfiguration>) => void = () => undefined;
    api.projectConfiguration
      .mockReturnValueOnce(
        new Promise((resolve) => {
          first = resolve;
        }),
      )
      .mockResolvedValue(
        projectConfiguration({
          skills: [skillItem({ name: "fresh", source: "project" })],
        }),
      );
    const { push } = await openConfiguration(api);
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    first(projectConfiguration());
    expect(await screen.findByText("No project skills yet")).toBeInTheDocument();
    expect(screen.getByText("No project servers yet")).toBeInTheDocument();

    push({ type: "configuration.changed", payload: { scope: "repo", repo: "narrative" } });
    push({ type: "configuration.changed", payload: { scope: "repo", repo: "cv-page" } });
    expect(await screen.findByText("fresh")).toBeInTheDocument();
    expect(api.projectConfiguration).toHaveBeenCalledTimes(2);
  });

  it("makes a project skill and opens it", async () => {
    const api = fakeApi();
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: "New skill" }));

    const form = screen.getByRole("dialog", { name: "New skill" });
    expect(form).toHaveTextContent(
      "Made in the project's .claude/skills, which only Claude reads.",
    );
    await user.type(within(form).getByLabelText("Name"), "publish-cv");
    await user.click(within(form).getByRole("button", { name: "Create" }));

    expect(api.createProjectSkill).toHaveBeenCalledWith("cv-page", "publish-cv", "");
    expect(await screen.findByRole("dialog", { name: "publish-cv" })).toHaveTextContent(
      "~/cv-page/.claude/skills/publish-cv/SKILL.md · project skill",
    );
  });

  it("adds a server to the project's .mcp.json, and removes one", async () => {
    const api = fakeApi();
    const withServer = projectConfiguration({
      mcp_servers: [{ name: "lighthouse", summary: "npx lighthouse-mcp", transport: "stdio" }],
    });
    api.projectConfiguration.mockResolvedValue(withServer);
    api.putProjectMcpServer.mockResolvedValue(withServer);
    const { user } = await openConfiguration(api);

    await user.click(await screen.findByRole("button", { name: "Add server" }));
    const form = screen.getByRole("dialog", { name: "Add server" });
    expect(form).toHaveTextContent("Saved in the project's .mcp.json, which only Claude reads.");
    await user.type(within(form).getByLabelText("Name"), "docs");
    await user.click(within(form).getByRole("button", { name: "HTTP" }));
    await user.type(within(form).getByLabelText("URL"), "https://docs.example.com/mcp");
    await user.click(within(form).getByRole("button", { name: "Add" }));
    expect(api.putProjectMcpServer).toHaveBeenCalledWith("cv-page", "docs", {
      transport: "http",
      url: "https://docs.example.com/mcp",
      headers: {},
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Add server" })).toBeNull();
    });

    await user.click(screen.getByRole("button", { name: "Remove lighthouse" }));
    expect(api.deleteProjectMcpServer).toHaveBeenCalledWith("cv-page", "lighthouse");
  });
});
