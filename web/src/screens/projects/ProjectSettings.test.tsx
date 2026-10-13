import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { RepoConfig, Session } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

async function openSettings(
  repos: RepoConfig[] = [repo("todo-ui"), repo("narwhal")],
  sessions: Session[] = [],
  api: FakeApi = fakeApi(),
) {
  api.repos.mockResolvedValue(repos);
  api.sessions.mockImplementation((archived) =>
    Promise.resolve(sessions.filter((s) => (s.archived_at !== null) === archived)),
  );
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  await rendered.user.click(screen.getByRole("button", { name: "Settings for todo-ui" }));
  const sheet = await screen.findByRole("dialog", { name: "todo-ui" });
  return { ...rendered, sheet };
}

describe("project settings", () => {
  it("show where the project is and set where its new chats work", async () => {
    const { user, api, sheet } = await openSettings();
    const modes = within(sheet).getByRole("group", { name: "New chats work in" });
    const pressed = () =>
      within(modes)
        .getAllByRole("button")
        .filter((b) => b.getAttribute("aria-pressed") === "true")
        .map((b) => b.textContent);

    expect(sheet).toHaveTextContent("/Users/me/todo-ui");
    expect(pressed()).toEqual(["Worktree"]);
    await user.click(within(modes).getByRole("button", { name: "In place" }));
    await waitFor(() => {
      expect(pressed()).toEqual(["In place"]);
    });
    await user.click(within(modes).getByRole("button", { name: "Agent default" }));

    const worktree = repo("todo-ui").worktree;
    expect(api.updateWorktree.mock.calls).toEqual([
      ["todo-ui", { ...worktree, default: false }],
      ["todo-ui", { ...worktree, default: null }],
    ]);
    await waitFor(() => {
      expect(pressed()).toEqual(["Agent default"]);
    });
  });

  it("save the files linked into worktrees and the setup commands", async () => {
    const { user, api, sheet } = await openSettings();
    const links = within(sheet).getByLabelText("Linked files");
    const setup = within(sheet).getByLabelText("Setup commands");

    await user.type(links, ".env{Enter}  {Enter} .env.local ");
    await user.type(setup, "npm ci");
    await user.click(within(sheet).getByRole("button", { name: "Save" }));

    expect(api.updateRepo).toHaveBeenCalledWith("todo-ui", {
      link: [".env", ".env.local"],
      setup: ["npm ci"],
    });
    expect(await screen.findByText("Saved todo-ui")).toBeInTheDocument();
    expect(links).toHaveValue(".env\n.env.local");
  });

  it("keep what was typed when saving is refused", async () => {
    const api = fakeApi();
    api.updateRepo.mockRejectedValueOnce(
      new ApiError(422, "link '../x' must be a relative path inside the repository"),
    );
    const { user, sheet } = await openSettings(undefined, undefined, api);
    const links = within(sheet).getByLabelText("Linked files");

    await user.type(links, "../x");
    await user.click(within(sheet).getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("link '../x' must be a relative path inside the repository"),
    ).toBeInTheDocument();
    expect(links).toHaveValue("../x");
    expect(within(sheet).getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("show the saved links and setup, and keep the worktree default when it fails", async () => {
    const configured = {
      ...repo("todo-ui"),
      worktree: {
        default: null,
        link: [".env"],
        setup: ["npm ci", "npm run db"],
        setup_timeout_seconds: 60,
      },
    };
    const api = fakeApi();
    api.updateWorktree.mockRejectedValueOnce(new ApiError(500, "Could not write the config"));
    const { user, sheet } = await openSettings([configured], undefined, api);

    expect(within(sheet).getByLabelText("Linked files")).toHaveValue(".env");
    expect(within(sheet).getByLabelText("Setup commands")).toHaveValue("npm ci\nnpm run db");
    await user.click(within(sheet).getByRole("button", { name: "Worktree" }));

    expect(await screen.findByText("Could not write the config")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Agent default" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("offer only Remove for a plain folder", async () => {
    const folder = { ...repo("todo-ui"), git: false, default_branch: null };
    const { sheet } = await openSettings([folder]);

    expect(sheet).toHaveTextContent("A plain folder: its chats work in place.");
    expect(within(sheet).queryByRole("group", { name: "New chats work in" })).toBeNull();
    expect(within(sheet).queryByLabelText("Linked files")).toBeNull();
    expect(within(sheet).getByRole("button", { name: "Remove project" })).toBeInTheDocument();
  });

  it("remove a project without chats after confirming; its folder stays", async () => {
    const { user, api, sheet } = await openSettings();

    await user.click(within(sheet).getByRole("button", { name: "Remove project" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(api.removeRepo).not.toHaveBeenCalled();
    await user.click(within(sheet).getByRole("button", { name: "Remove project" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Remove todo-ui?" });
    expect(confirm).toHaveTextContent(
      "harness forgets this project. Its folder stays on your Mac, untouched.",
    );
    await user.click(within(confirm).getByRole("button", { name: "Remove" }));

    expect(api.removeRepo).toHaveBeenCalledWith("todo-ui", false);
    expect(await screen.findByText("Removed todo-ui")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "todo-ui" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /todo-ui/ })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /narwhal/ })).toHaveAttribute("aria-selected", "true");
  });

  it("say that removing deletes the project's chats, and delete them", async () => {
    const chats = [
      session({ id: "a" }),
      session({ id: "b", archived_at: "2026-10-06T11:00:00Z" }),
      session({ id: "c", repo: "narwhal" }),
    ];
    const { user, api, sheet } = await openSettings(undefined, chats);

    await user.click(within(sheet).getByRole("button", { name: "Remove project" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Remove todo-ui?" });
    expect(confirm).toHaveTextContent(
      "Its 2 chats are deleted too, with their worktrees and branches.",
    );
    await user.click(within(confirm).getByRole("button", { name: "Remove" }));

    expect(api.removeRepo).toHaveBeenCalledWith("todo-ui", true);
    await user.click(await screen.findByRole("tab", { name: /narwhal/ }));
    expect(screen.getByRole("button", { name: /^Validate contact form,/ })).toBeInTheDocument();
  });

  it("say one chat in the singular, and keep the project when removing fails", async () => {
    const api = fakeApi();
    api.removeRepo.mockRejectedValueOnce(
      new ApiError(409, "repo 'todo-ui' still has 2 session(s)"),
    );
    const { user, sheet } = await openSettings(undefined, [session()], api);

    await user.click(within(sheet).getByRole("button", { name: "Remove project" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Remove todo-ui?" });
    expect(confirm).toHaveTextContent("Its chat is deleted too, with its worktree and branch.");
    await user.click(within(confirm).getByRole("button", { name: "Remove" }));

    expect(await screen.findByText("repo 'todo-ui' still has 2 session(s)")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "todo-ui" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /todo-ui/ })).toBeInTheDocument();
  });

  it("close when the project is removed on the Mac", async () => {
    const { push } = await openSettings();

    push({ type: "repo.removed", payload: { name: "todo-ui" } });

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "todo-ui" })).not.toBeInTheDocument();
    });
  });
});
