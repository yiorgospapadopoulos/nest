import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { Approval, NestEvent, Session } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { commandList, detail, event, plan, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

interface Setup {
  chat?: Session;
  events?: NestEvent[];
  approvals?: Approval[];
  api?: FakeApi;
}

async function openChat({
  chat = session(),
  events = [],
  approvals = [],
  api = fakeApi(),
}: Setup = {}) {
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.approvals.mockResolvedValue(approvals);
  api.session.mockResolvedValue(detail(chat));
  api.sessionEvents.mockResolvedValue(events);
  api.resolveApproval.mockImplementation((id) =>
    Promise.resolve({ ...defined(approvals.find((a) => a.id === id)), status: "resolved" }),
  );
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  return { ...rendered, field: screen.getByLabelText("Message") };
}

const options = (name: string) =>
  within(screen.getByRole("listbox", { name }))
    .getAllByRole("option")
    .map((o) => o.textContent);

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("slash commands", () => {
  it("suggests the chat's commands after a leading slash and completes one", async () => {
    const { user, api, field } = await openChat();

    await user.type(field, "/");
    expect(await screen.findByRole("listbox", { name: "Commands" })).toBeInTheDocument();
    // With Nest's own commands, by name (B59).
    expect(options("Commands")).toEqual([
      "/clearClear the conversation",
      "/compact [focus]Summarise the conversation",
      "/mcpShow MCP servers and connectors",
      "/model [model]Set the model for this chat",
      "/permissionsChoose the permission mode",
      "/resume [search]Resume another chat",
      "/reviewReview a pull request",
      "/security-review",
    ]);
    await user.type(field, "rev");
    expect(options("Commands")).toEqual(["/reviewReview a pull request", "/security-review"]);
    await user.click(screen.getByRole("option", { name: /security-review/ }));
    expect(field).toHaveValue("/security-review ");
    expect(field).toHaveFocus();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

    await user.clear(field);
    await user.type(field, "/zzz");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    await user.clear(field);
    await user.type(field, "hi /c");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(api.sessionCommands).toHaveBeenCalledTimes(1);
    expect(api.sessionCommands).toHaveBeenCalledWith("s1");

    await user.clear(field);
    await user.type(field, "/compact keep the API notes{Enter}");
    expect(api.sendMessage).toHaveBeenCalledWith("s1", "/compact keep the API notes", []);
  });

  it("moves through the suggestions with the arrow keys and picks with Enter or Tab", async () => {
    const { user, api, field } = await openChat();

    await user.type(field, "/c");
    await screen.findByRole("listbox", { name: "Commands" });
    const selected = () => screen.getByRole("option", { selected: true }).textContent;
    expect(selected()).toMatch(/^\/clear/);
    await user.keyboard("{ArrowDown}");
    expect(selected()).toMatch(/^\/compact/);
    await user.keyboard("{ArrowUp}{ArrowUp}");
    expect(selected()).toMatch(/^\/security-review/);
    await user.keyboard("{ArrowDown}");
    expect(selected()).toMatch(/^\/clear/);
    await user.keyboard("{ArrowUp}{Enter}");
    expect(field).toHaveValue("/security-review ");
    expect(api.sendMessage).not.toHaveBeenCalled();

    await user.clear(field);
    await user.type(field, "/co{Tab}");
    expect(field).toHaveValue("/compact ");
    expect(field).toHaveFocus();
  });

  it("closes when the field loses focus and opens again on return", async () => {
    const { user, field } = await openChat();

    await user.type(field, "/");
    await screen.findByRole("listbox", { name: "Commands" });
    await user.click(screen.getByRole("heading", { name: "Validate contact form" }));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    await user.click(field);
    expect(screen.getByRole("listbox", { name: "Commands" })).toBeInTheDocument();
  });

  it("shows only Nest's own commands when the list cannot be loaded", async () => {
    const api = fakeApi();
    api.sessionCommands.mockRejectedValue(new ApiError(500, "boom"));
    const { user, field } = await openChat({ api });

    await user.type(field, "/");
    await waitFor(() => {
      expect(api.sessionCommands).toHaveBeenCalled();
    });
    expect(options("Commands")).toEqual([
      "/mcpShow MCP servers and connectors",
      "/model [model]Set the model for this chat",
      "/permissionsChoose the permission mode",
      "/resume [search]Resume another chat",
    ]);
    expect(screen.queryByText("boom")).not.toBeInTheDocument();
  });

  it("goes back to pairing when the device was revoked", async () => {
    const api = fakeApi();
    api.sessionCommands.mockRejectedValue(new ApiError(401, "unknown device"));
    const { user, field } = await openChat({ api });

    await user.type(field, "/");
    expect(await screen.findByRole("heading", { name: /Pair/ })).toBeInTheDocument();
  });

  it("uses the project's last known commands in a new chat", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("cv-page")]);
    api.repoCommands.mockResolvedValue(
      commandList({
        source: "repo",
        commands: [{ name: "init", description: null, argument_hint: null }],
      }),
    );
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));

    await user.type(screen.getByLabelText("Message"), "/");
    expect(await screen.findByRole("option", { name: "/init" })).toBeInTheDocument();
    expect(api.repoCommands).toHaveBeenCalledWith("cv-page");
    expect(api.sessionCommands).not.toHaveBeenCalled();
  });
});

describe("file mentions", () => {
  it("suggests files for the word after @ and inserts the chosen path", async () => {
    const api = fakeApi();
    api.files.mockResolvedValue({ files: ["src/app.py", "src/api.py"] });
    const { user, field } = await openChat({ api });

    await user.type(field, "Look at @sr");
    expect(await screen.findByRole("listbox", { name: "Files" })).toBeInTheDocument();
    expect(api.files).toHaveBeenLastCalledWith("s1", "sr");
    expect(options("Files")).toEqual(["src/app.py", "src/api.py"]);
    await user.click(screen.getByRole("option", { name: "src/app.py" }));
    expect(field).toHaveValue("Look at @src/app.py ");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

    await user.type(field, "and me@x");
    await act(() => new Promise((done) => setTimeout(done, 200)));
    expect(api.files).toHaveBeenCalledTimes(1);
  });

  it("shows the answer to the latest request only", async () => {
    const api = fakeApi();
    const slow = deferred<{ files: string[] }>();
    api.files.mockReturnValueOnce(slow.promise).mockResolvedValueOnce({ files: ["ab.ts"] });
    const { user, field } = await openChat({ api });

    await user.type(field, "@a");
    await waitFor(() => {
      expect(api.files).toHaveBeenCalledWith("s1", "a");
    });
    await user.type(field, "b");
    expect(await screen.findByRole("option", { name: "ab.ts" })).toBeInTheDocument();
    expect(api.files).toHaveBeenLastCalledWith("s1", "ab");
    await act(async () => {
      slow.resolve({ files: ["a.ts"] });
      await slow.promise;
    });
    expect(options("Files")).toEqual(["ab.ts"]);
  });

  it("shows nothing when the files cannot be listed", async () => {
    const api = fakeApi();
    api.files.mockRejectedValue(new ApiError(404, "unknown session"));
    const { user, field } = await openChat({ api });

    await user.type(field, "@x");
    await waitFor(() => {
      expect(api.files).toHaveBeenCalled();
    });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.queryByText("unknown session")).not.toBeInTheDocument();
  });

  it("is not offered before the chat exists", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("cv-page")]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));

    await user.type(screen.getByLabelText("Message"), "@src");
    await act(() => new Promise((done) => setTimeout(done, 200)));
    expect(api.files).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

describe("plan approval", () => {
  const created = (a: Approval) =>
    event({ id: 1, type: "approval.created", payload: { approval: { ...a } } });

  it("shows the plan in the chat and approves it", async () => {
    const p = plan();
    const { user, api } = await openChat({
      chat: session({ state: "waiting", permission_mode: "plan" }),
      approvals: [p],
      events: [created(p)],
    });

    const card = screen.getByRole("group", { name: "Plan ready" });
    expect(within(card).getByRole("heading", { name: "Plan", level: 4 })).toBeInTheDocument();
    expect(within(card).getByText("zod").tagName).toBe("STRONG");
    expect(screen.getByRole("img", { name: "Plan ready" })).toHaveClass("dot s-wait");
    const modes = within(card).getByRole("radiogroup", { name: "Then" });
    expect(within(modes).getByRole("radio", { name: "Auto-accept edits" })).toBeChecked();
    await user.click(within(card).getByRole("button", { name: "Approve plan" }));

    expect(api.resolveApproval).toHaveBeenCalledWith("q4", {
      decision: "approve",
      mode: "acceptEdits",
    });
    expect(await screen.findByText("Plan approved")).toBeInTheDocument();
  });

  it("approves a plan to go on with edits approved manually, or in Auto", async () => {
    const p = plan();
    const second = plan({ id: "q9" });
    const { user, api, push } = await openChat({ approvals: [p], events: [created(p)] });
    const card = screen.getByRole("group", { name: "Plan ready" });
    const modes = within(card).getByRole("radiogroup", { name: "Then" });
    await waitFor(() => {
      expect(
        within(modes)
          .getAllByRole("radio")
          .map((r) => r.textContent),
      ).toEqual(["Auto-accept edits", "Approve edits manually", "Auto"]);
    });

    await user.click(within(modes).getByRole("radio", { name: "Approve edits manually" }));
    expect(within(modes).getByRole("radio", { name: "Auto-accept edits" })).not.toBeChecked();
    await user.click(within(card).getByRole("button", { name: "Approve plan" }));
    push({
      id: 2,
      session_id: "s1",
      type: "approval.created",
      payload: { approval: { ...second } },
    });
    const next = await screen.findByRole("group", { name: "Plan ready" });
    await user.click(within(next).getByRole("radio", { name: "Auto" }));
    await user.click(within(next).getByRole("button", { name: "Approve plan" }));

    expect(api.resolveApproval.mock.calls).toEqual([
      ["q4", { decision: "approve", mode: "default" }],
      ["q9", { decision: "approve", mode: "auto" }],
    ]);
  });

  it("offers Auto after a plan only for models that take it", async () => {
    const p = plan();
    const { api } = await openChat({
      chat: session({ model: "haiku" }),
      approvals: [p],
      events: [created(p)],
    });
    await waitFor(() => {
      expect(api.models).toHaveBeenCalled();
    });

    const modes = screen.getByRole("radiogroup", { name: "Then" });
    expect(within(modes).getAllByRole("radio")).toHaveLength(2);
  });

  it("keeps planning with an optional note", async () => {
    const p = plan();
    const { user, api } = await openChat({ approvals: [p], events: [created(p)] });
    const card = screen.getByRole("group", { name: "Plan ready" });

    await user.click(within(card).getByRole("button", { name: "Keep planning" }));
    const note = within(card).getByLabelText("Note for Claude");
    expect(note).toHaveFocus();
    await user.click(within(card).getByRole("button", { name: "Cancel" }));
    expect(within(card).queryByLabelText("Note for Claude")).not.toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Keep planning" }));
    await user.type(within(card).getByLabelText("Note for Claude"), "  Smaller steps {Enter}");

    expect(api.resolveApproval).toHaveBeenCalledWith("q4", {
      decision: "keep_planning",
      message: "Smaller steps",
    });
    expect(await screen.findByText("Claude keeps planning")).toBeInTheDocument();
  });

  it("keeps planning without a note from the Inbox", async () => {
    const p = plan({
      payload: { plan: Array.from({ length: 30 }, (_, i) => `- Step ${String(i)}`).join("\n") },
    });
    const api = fakeApi();
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [session()]));
    api.approvals.mockResolvedValue([p]);
    api.resolveApproval.mockRejectedValueOnce(new ApiError(409, "already resolved"));
    api.resolveApproval.mockResolvedValue({ ...p, status: "resolved" });
    const { user } = await renderApp({ api });

    const card = screen.getByRole("article", { name: "Plan: Validate contact form" });
    // Rows start closed (B102 item 10).
    await user.click(within(card).getByRole("button", { name: "Show details" }));
    const more = within(card).getByRole("button", { name: "Show all" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(card.querySelector(".plan.clip")).not.toBeNull();
    await user.click(more);
    expect(within(card).getByRole("button", { name: "Show less" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(card.querySelector(".plan.clip")).toBeNull();

    await user.click(within(card).getByRole("button", { name: "Keep planning" }));
    await user.click(within(card).getByRole("button", { name: "Keep planning" }));
    expect(await screen.findByText("already resolved")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Keep planning" }));

    expect(api.resolveApproval).toHaveBeenLastCalledWith("q4", {
      decision: "keep_planning",
      message: null,
    });
    expect(await screen.findByText("Nothing needs you.")).toBeInTheDocument();
  });

  it("approves from the Inbox, with a short plan shown whole", async () => {
    const p = plan();
    const api = fakeApi();
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [session()]));
    api.approvals.mockResolvedValue([p]);
    api.resolveApproval.mockResolvedValue({ ...p, status: "resolved" });
    const { user } = await renderApp({ api });

    const card = screen.getByRole("article", { name: "Plan: Validate contact form" });
    // Rows start closed (B102 item 10).
    await user.click(within(card).getByRole("button", { name: "Show details" }));
    expect(within(card).queryByRole("button", { name: "Show all" })).not.toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Approve plan" }));
    expect(api.resolveApproval).toHaveBeenCalledWith("q4", {
      decision: "approve",
      mode: "acceptEdits",
    });
  });
});

describe("context meter", () => {
  const context = { percent: 41.4, used: 82_000, limit: 200_000 };

  it("shows how full the context is and compacts on request", async () => {
    const { user, api, field, push } = await openChat({ chat: session({ context }) });

    const meter = screen.getByRole("button", { name: "Context: 41% used" });
    // Short, as the Mac's, so the place next to the mic keeps its room (B102).
    expect(meter).toHaveTextContent(/^41%$/);
    await user.type(field, "Draft");
    await user.click(meter);
    const sheet = screen.getByRole("dialog", { name: "Context" });
    expect(within(sheet).getByText("82k of 200k tokens")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("menuitem", { name: /Compact/ }));

    expect(api.sendMessage).toHaveBeenCalledWith("s1", "/compact", []);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(field).toHaveValue("Draft");

    push({
      id: 7,
      session_id: "s1",
      type: "session.context",
      payload: { context: { percent: 3, used: 6000, limit: 200_000 } },
    });
    expect(screen.getByRole("button", { name: "Context: 3% used" })).toBeInTheDocument();
    push({ id: 8, session_id: "s1", type: "session.context", payload: { context: null } });
    expect(screen.queryByRole("button", { name: /^Context/ })).not.toBeInTheDocument();
  });

  it("says when Claude Code has the chat open", async () => {
    const api = fakeApi();
    api.sendMessage.mockRejectedValueOnce(
      new ApiError(409, "open elsewhere", "open_in_claude_code"),
    );
    const { user } = await openChat({ chat: session({ context }), api });

    await user.click(screen.getByRole("button", { name: "Context: 41% used" }));
    await user.click(screen.getByRole("menuitem", { name: /Compact/ }));
    expect(
      await screen.findByText("This chat is open in Claude Code right now. Close it there first."),
    ).toBeInTheDocument();
  });

  it("closes without compacting", async () => {
    const { user, api } = await openChat({ chat: session({ context }) });

    await user.click(screen.getByRole("button", { name: "Context: 41% used" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.sendMessage).not.toHaveBeenCalled();
  });

  it("is hidden until a turn reports it", async () => {
    await openChat();
    expect(screen.queryByRole("button", { name: /^Context/ })).not.toBeInTheDocument();
  });
});
