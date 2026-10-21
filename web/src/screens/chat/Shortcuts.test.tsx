import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { RepoConfig, Session, ShellResult } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { detail, event, pixie, repo, session } from "../../test/fixtures.ts";
import { openPixie } from "../../test/pixies.ts";
import { renderApp } from "../../test/render.tsx";

const CONTEXT =
  "<bash-input>git status --short</bash-input>\n<bash-stdout> M src/app.py</bash-stdout><bash-stderr></bash-stderr>";

function shell(overrides: Partial<ShellResult> = {}): ShellResult {
  return {
    command: "git status --short",
    exit_code: 0,
    output: " M src/app.py\n",
    truncated: false,
    timed_out: false,
    context: CONTEXT,
    ...overrides,
  };
}

async function openChat({
  chat = session(),
  project = repo("cv-page"),
  api = fakeApi(),
}: { chat?: Session; project?: RepoConfig; api?: FakeApi } = {}) {
  api.repos.mockResolvedValue([project]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  return { ...rendered, field: screen.getByLabelText("Message") };
}

const pixieChat = session({ id: "c1", title: "Tester", repo: "pixie:p1", pixie_id: "p1" });

async function openPixieChat(api = fakeApi()) {
  api.session.mockResolvedValue(detail(pixieChat));
  const rendered = await openPixie(api, pixie({ chat_session_id: "c1" }));
  await waitFor(() => {
    expect(api.session).toHaveBeenCalledWith("c1");
  });
  return { ...rendered, field: screen.getByLabelText("Message") };
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const row = (command: string) =>
  defined(screen.getByText(`! ${command}`).closest<HTMLElement>(".bash"));

describe("! bash mode (B59)", () => {
  it("runs the command in the chat's folder and shows it with its output", async () => {
    const api = fakeApi();
    const reply = deferred<ShellResult>();
    api.shell.mockReturnValue(reply.promise);
    const { user, field } = await openChat({ api });

    await user.type(field, "!");
    expect(screen.getByText("Bash mode")).toBeInTheDocument();
    expect(field.closest(".comp")).toHaveClass("bash");
    await user.type(field, "git status --short{Enter}");

    expect(api.shell).toHaveBeenCalledWith("s1", "git status --short");
    expect(api.sendMessage).not.toHaveBeenCalled();
    expect(field).toHaveValue("");
    expect(screen.queryByText("Bash mode")).not.toBeInTheDocument();
    const running = within(row("git status --short")).getByRole("status");
    expect(running).toHaveTextContent("Running");
    expect(running.querySelector(".ff")).not.toBeNull();

    reply.resolve(shell());
    expect(await screen.findByText("M src/app.py", { exact: false })).toBeInTheDocument();
    expect(within(row("git status --short")).queryByRole("status")).toBeNull();
  });

  it.each([
    [{ exit_code: 1 }, "exit 1"],
    [{ exit_code: null, timed_out: true }, "timed out after 2 minutes"],
    [{ truncated: true }, "output cut"],
  ])("says how the command ended: %o", async (ended, line) => {
    const api = fakeApi();
    api.shell.mockResolvedValue(shell({ ...ended, command: "make" }));
    const { user, field } = await openChat({ api });

    await user.type(field, "!make{Enter}");

    expect(await within(row("make")).findByText(line)).toBeInTheDocument();
  });

  it("shows a failure in the row", async () => {
    const api = fakeApi();
    api.shell.mockRejectedValue(new ApiError(409, "The chat's folder is gone"));
    const { user, field } = await openChat({ api });

    await user.type(field, "!ls{Enter}");

    expect(await within(row("ls")).findByText("The chat's folder is gone")).toBeInTheDocument();
  });

  it("goes back to pairing when the device is no longer known", async () => {
    const api = fakeApi();
    api.shell.mockRejectedValue(new ApiError(401, "unknown device"));
    const { user, field } = await openChat({ api });

    await user.type(field, "!ls{Enter}");

    expect(await screen.findByRole("heading", { name: /Pair/ })).toBeInTheDocument();
  });

  it("does not run an empty command", async () => {
    const { user, api, field } = await openChat();

    await user.type(field, "!  {Enter}");

    expect(api.shell).not.toHaveBeenCalled();
    expect(api.sendMessage).not.toHaveBeenCalled();
  });

  it("gives Claude what ran with the next message only", async () => {
    const api = fakeApi();
    api.shell.mockResolvedValue(shell());
    const { user, field, push } = await openChat({ api });
    await user.type(field, "!git status --short{Enter}");
    await screen.findByText("M src/app.py", { exact: false });

    // A slash command goes as typed; what ran waits for a message.
    await user.type(field, "/review");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(api.sendMessage).toHaveBeenLastCalledWith("s1", "/review", []);
    await user.type(field, "Why?{Enter}");
    expect(api.sendMessage).toHaveBeenLastCalledWith("s1", `${CONTEXT}\n\nWhy?`, []);
    await waitFor(() => {
      expect(screen.queryByText("! git status --short")).not.toBeInTheDocument();
    });

    push(
      event({
        id: 9,
        type: "session.user_message",
        payload: { text: `${CONTEXT}\n\nWhy?`, attachments: [] },
      }),
    );
    expect(row("git status --short")).toHaveTextContent("M src/app.py");
    expect(screen.getByText("Why?")).toBeInTheDocument();
    expect(screen.queryByText(/bash-input/)).not.toBeInTheDocument();

    await user.type(field, "Thanks{Enter}");
    expect(api.sendMessage).toHaveBeenLastCalledWith("s1", "Thanks", []);
  });

  it("sends what finished: a failed command is dropped, a running one waits", async () => {
    const api = fakeApi();
    const slow = deferred<ShellResult>();
    api.shell
      .mockRejectedValueOnce(new ApiError(409, "The chat's folder is gone"))
      .mockReturnValueOnce(slow.promise);
    const { user, field } = await openChat({ api });
    await user.type(field, "!ls{Enter}");
    await within(row("ls")).findByText("The chat's folder is gone");
    await user.type(field, "!make{Enter}");

    await user.type(field, "Hi{Enter}");
    expect(api.sendMessage).toHaveBeenLastCalledWith("s1", "Hi", []);
    await waitFor(() => {
      expect(screen.queryByText("! ls")).not.toBeInTheDocument();
    });
    expect(screen.getByText("! make")).toBeInTheDocument();

    slow.resolve(shell({ command: "make", context: "<make>" }));
    await within(row("make")).findByText("M src/app.py", { exact: false });
    await user.type(field, "Then?{Enter}");
    expect(api.sendMessage).toHaveBeenLastCalledWith("s1", "<make>\n\nThen?", []);
  });

  it("keeps the command for the next message when sending fails", async () => {
    const api = fakeApi();
    api.shell.mockResolvedValue(shell());
    api.sendMessage.mockRejectedValueOnce(new ApiError(500, "boom"));
    const { user, field } = await openChat({ api });
    await user.type(field, "!git status --short{Enter}");
    await screen.findByText("M src/app.py", { exact: false });

    await user.type(field, "Why?{Enter}");
    expect(await screen.findByText("boom")).toBeInTheDocument();

    expect(screen.getByText("! git status --short")).toBeInTheDocument();
  });

  it("is plain text in a chat a pixie started", async () => {
    const { user, api, field } = await openChat({ chat: session({ started_by_pixie: "p1" }) });

    await user.type(field, "!ls");
    expect(screen.queryByText("Bash mode")).not.toBeInTheDocument();
    await user.type(field, "{Enter}");

    expect(api.shell).not.toHaveBeenCalled();
    expect(api.sendMessage).toHaveBeenCalledWith("s1", "!ls", []);
  });

  it("is plain text in a pixie's chat", async () => {
    const { user, api, field } = await openPixieChat();

    await user.type(field, "!ls{Enter}");

    expect(api.shell).not.toHaveBeenCalled();
    expect(api.sendToPixie).toHaveBeenCalledWith("p1", "!ls");
  });
});

describe("# memory (B59)", () => {
  it("saves to project memory and tells where", async () => {
    const api = fakeApi();
    api.remember.mockResolvedValue({
      path: "/Users/me/cv-page/CLAUDE.md",
      scope: "project",
      line: "- Run make check",
    });
    const { user, field } = await openChat({ api });

    await user.type(field, "#Run make check");
    expect(screen.getByText("Memory")).toBeInTheDocument();
    await user.type(field, "{Enter}");
    const ask = screen.getByRole("dialog", { name: "Save to memory" });
    await user.click(within(ask).getByRole("menuitem", { name: /^Project memory/ }));

    expect(api.remember).toHaveBeenCalledWith("s1", "Run make check", "project");
    expect(
      await screen.findByText("Saved to project memory: /Users/me/cv-page/CLAUDE.md"),
    ).toBeInTheDocument();
    expect(field).toHaveValue("");
    expect(api.sendMessage).not.toHaveBeenCalled();
  });

  it("saves to user memory", async () => {
    const api = fakeApi();
    api.remember.mockResolvedValue({ path: "/u/CLAUDE.md", scope: "user", line: "- x" });
    const { user, field } = await openChat({ api });

    await user.type(field, "# Prefer small commits{Enter}");
    await user.click(screen.getByRole("menuitem", { name: /^User memory/ }));

    expect(api.remember).toHaveBeenCalledWith("s1", "Prefer small commits", "user");
    expect(await screen.findByText("Saved to user memory: /u/CLAUDE.md")).toBeInTheDocument();
  });

  it("keeps the text when saving fails or is cancelled", async () => {
    const api = fakeApi();
    api.remember.mockRejectedValueOnce(new ApiError(404, "unknown repo"));
    const { user, field } = await openChat({ api });

    await user.type(field, "#Note{Enter}");
    await user.click(screen.getByRole("menuitem", { name: /^Project memory/ }));
    expect(await screen.findByText("unknown repo")).toBeInTheDocument();
    expect(field).toHaveValue("#Note");

    await user.type(field, "{Enter}");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(field).toHaveValue("#Note");
    expect(api.remember).toHaveBeenCalledTimes(1);
  });

  it("does not save an empty memory", async () => {
    const { user, api, field } = await openChat();

    await user.type(field, "# {Enter}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.sendMessage).not.toHaveBeenCalled();
  });

  it("sends a Markdown heading as a message", async () => {
    const { user, api, field } = await openChat();

    await user.type(field, "## Plan{Enter}");

    expect(screen.queryByText("Memory")).not.toBeInTheDocument();
    expect(api.sendMessage).toHaveBeenCalledWith("s1", "## Plan", []);
  });

  it("offers only user memory in a pixie's chat", async () => {
    const api = fakeApi();
    api.remember.mockResolvedValue({ path: "/u/CLAUDE.md", scope: "user", line: "- x" });
    const { user, field } = await openPixieChat(api);

    await user.type(field, "#Be brief{Enter}");
    expect(screen.queryByRole("menuitem", { name: /^Project memory/ })).toBeNull();
    await user.click(screen.getByRole("menuitem", { name: /^User memory/ }));

    expect(api.remember).toHaveBeenCalledWith("c1", "Be brief", "user");
    expect(api.sendToPixie).not.toHaveBeenCalled();
  });

  it("is plain text before a pixie has a chat", async () => {
    const api = fakeApi();
    const { user } = await openPixie(api);

    await user.type(screen.getByLabelText("Message"), "#hi{Enter}");

    expect(api.sendToPixie).toHaveBeenCalledWith("p1", "#hi");
  });
});

describe("@ files everywhere (B59)", () => {
  it("are offered in a plain folder", async () => {
    const api = fakeApi();
    api.files.mockResolvedValue({ files: ["todo.md"] });
    const { user, field } = await openChat({ api, project: { ...repo("cv-page"), git: false } });

    await user.type(field, "@to");

    expect(await screen.findByRole("option", { name: /todo\.md/ })).toBeInTheDocument();
    expect(api.files).toHaveBeenCalledWith("s1", "to");
  });

  it("are offered in a pixie's chat, without its commands", async () => {
    const api = fakeApi();
    api.files.mockResolvedValue({ files: ["notes/plan.md"] });
    const { user, field } = await openPixieChat(api);

    await user.type(field, "@pl");
    expect(await screen.findByRole("option", { name: /notes\/plan\.md/ })).toBeInTheDocument();
    expect(api.files).toHaveBeenCalledWith("c1", "pl");

    await user.clear(field);
    await user.type(field, "/");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
