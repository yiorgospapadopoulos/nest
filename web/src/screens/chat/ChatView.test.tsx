import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type {
  Approval,
  BackgroundItem,
  NestEvent,
  Session,
  TrackedAgent,
} from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import {
  approval,
  check,
  detail,
  event,
  mergeApproval,
  prStatus,
  question,
  repo,
  review,
  session,
} from "../../test/fixtures.ts";
import { fixedMedia } from "../../test/motion.ts";
import { renderApp } from "../../test/render.tsx";

interface Setup {
  chat?: Session;
  events?: NestEvent[];
  agents?: TrackedAgent[];
  approvals?: Approval[];
}

async function openChat({
  chat = session(),
  events = [],
  agents = [],
  approvals = [],
}: Setup = {}) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.approvals.mockResolvedValue(approvals);
  api.session.mockResolvedValue(detail({ ...chat, agents }));
  api.sessionEvents.mockResolvedValue(events);
  api.updateSession.mockImplementation((_id, body) =>
    Promise.resolve({ ...chat, ...body, archived_at: body.archived === true ? "x" : null }),
  );
  api.resolveApproval.mockImplementation((id) =>
    Promise.resolve({ ...defined(approvals.find((a) => a.id === id)), status: "resolved" }),
  );
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  return rendered;
}

/** Opens the pending review's changes from the bar above the composer. */
async function openReview(user: Awaited<ReturnType<typeof openChat>>["user"]) {
  const bar = screen.getByRole("group", { name: "Changes to review" });
  await user.click(within(bar).getByRole("button", { name: "Review" }));
  return screen.findByRole("dialog", { name: "Validate contact form" });
}

/** Approving waits for the diff to load. */
async function enabled(button: HTMLElement) {
  await waitFor(() => {
    expect(button).toBeEnabled();
  });
  return button;
}

const agent = (overrides: Partial<TrackedAgent> = {}): TrackedAgent => ({
  id: "main",
  name: "main",
  description: null,
  status: "running",
  activity: "Edit src/a.ts",
  started_at: "2026-10-06T09:00:00Z",
  finished_at: null,
  steps: [],
  ...overrides,
});

const message = (id: number, blocks: unknown[]) =>
  event({
    id,
    type: "session.message",
    payload: { parent_tool_use_id: null, blocks: blocks as never },
  });

describe("chat view", () => {
  it("shows the header, transcript and live text", async () => {
    const { push } = await openChat({
      chat: session({ state: "running" }),
      agents: [agent()],
      events: [
        // An earlier turn that was stopped; the one after it still runs.
        event({ id: 1, type: "session.state", payload: { state: "interrupted" } }),
        event({
          id: 2,
          type: "session.user_message",
          payload: { text: "Fix it", attachments: [{ filename: "a.png" }] },
        }),
        message(3, [
          { type: "text", text: "Looking." },
          { type: "tool_use", id: "t1", name: "Read", input: { file_path: "/w/s1/a.ts" } },
          { type: "tool_use", id: "t2", name: "Grep", input: { pattern: "x" } },
          { type: "tool_use", id: "t3", name: "WebFetch", input: { url: "https://x.dev" } },
          { type: "tool_use", id: "t4", name: "TaskCreate", input: { subject: "Hidden task" } },
        ]),
        message(4, [
          { type: "tool_result", tool_use_id: "t1", content: "one\ntwo" },
          { type: "tool_result", tool_use_id: "t3", content: "404", is_error: true },
        ]),
      ],
    });

    const chat = within(screen.getByRole("region", { name: "Validate contact form" }));
    const heading = chat.getByRole("heading", { name: "Validate contact form" });
    // The status right after the name, fireflies while running, with no pill in the details row.
    const dot = chat.getByRole("img", { name: "Running" });
    expect(dot).toHaveClass("ff");
    expect(heading.nextElementSibling).toBe(dot);
    expect(chat.queryByText("Running")).not.toBeInTheDocument();
    expect(chat.getByTitle("Worktree agent/contact in /w/s1")).toBeInTheDocument();
    expect(screen.getByText("Fix it")).toBeInTheDocument();
    expect(screen.getByText("a.png")).toBeInTheDocument();
    expect(screen.getByText("Looking.")).toBeInTheDocument();
    expect(screen.getByText("2 lines").closest("details")).toHaveTextContent("one");
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("failed")).toHaveClass("tr bad");
    expect(screen.queryByText("Hidden task")).not.toBeInTheDocument();
    expect(screen.getByText("Interrupted")).toBeInTheDocument();
    expect(screen.getByText("Reading 1 file, searching 1 pattern, fetching 1 page")).toBeVisible();
    expect(screen.getByRole("button", { name: "Agents, 1 active" })).toHaveTextContent("1");

    push({ id: null, session_id: "s1", type: "session.delta", payload: { text: "Hel" } });
    push({ id: null, session_id: "s1", type: "session.delta", payload: { text: "lo" } });
    expect(screen.getByText("Hello")).toBeInTheDocument();
    push({
      id: 5,
      session_id: "s1",
      type: "session.message",
      payload: { blocks: [{ type: "text", text: "Hello there" }] },
    });
    // Also announced, in the chat's status region.
    expect(screen.getByText("Hello there", { selector: ".tx *" })).toBeInTheDocument();
    expect(screen.queryByText("Hello")).not.toBeInTheDocument();
    push({
      id: 6,
      session_id: "s1",
      type: "session.state",
      payload: { state: "idle", error: null },
    });
    expect(chat.getByRole("img", { name: "Idle" })).toHaveClass("dot s-idle");
    expect(screen.queryByText(/^Working/)).not.toBeInTheDocument();
  });

  it("says it is loading until the chat's history arrives", async () => {
    const api = fakeApi();
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [session()]));
    let arrive: (events: NestEvent[]) => void = () => undefined;
    api.sessionEvents.mockReturnValue(
      new Promise((resolve) => {
        arrive = resolve;
      }),
    );
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));
    await screen.findByRole("region", { name: "Validate contact form" });

    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(screen.queryByText("No messages yet")).not.toBeInTheDocument();
    await act(async () => {
      arrive([]);
      await Promise.resolve();
    });
    expect(await screen.findByText("No messages yet")).toBeInTheDocument();
    expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
  });

  it("shows an empty transcript, then working while it starts", async () => {
    const { push } = await openChat({ chat: session({ branch: null }) });

    expect(await screen.findByText("No messages yet")).toBeInTheDocument();
    push({
      id: 9,
      session_id: "s1",
      type: "session.state",
      payload: { state: "starting", error: null },
    });
    expect(screen.getByText("Working...")).toBeInTheDocument();
  });

  it("follows new content only at the bottom, with a way back to it", async () => {
    const { user, push, api } = await openChat({
      events: [message(1, [{ type: "text", text: "First" }])],
    });
    api.sendMessage.mockResolvedValue({ ...session({ state: "running" }), queued_message: null });
    const box = defined(screen.getByText("First").closest<HTMLElement>(".ch-tx"));
    Object.defineProperty(box, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(box, "clientHeight", { configurable: true, value: 300 });
    const said = (id: number, text: string) => {
      push({
        id,
        session_id: "s1",
        type: "session.message",
        payload: { blocks: [{ type: "text", text }] },
      });
    };
    expect(screen.queryByRole("button", { name: "Jump to latest" })).not.toBeInTheDocument();

    // 50 px above the bottom is reading, not following.
    box.scrollTop = 650;
    fireEvent.scroll(box);
    said(2, "Second");
    expect(box.scrollTop).toBe(650);
    await user.type(screen.getByLabelText("Message"), "Go on{Enter}");
    push({
      id: 3,
      session_id: "s1",
      type: "session.user_message",
      payload: { text: "Go on", attachments: [] },
    });
    expect(box.scrollTop).toBe(650);

    await user.click(screen.getByRole("button", { name: "Jump to latest" }));
    expect(box.scrollTop).toBe(1000);
    fireEvent.scroll(box);
    expect(screen.queryByRole("button", { name: "Jump to latest" })).not.toBeInTheDocument();

    // Within 40 px of the bottom keeps following.
    box.scrollTop = 670;
    fireEvent.scroll(box);
    said(4, "Third");
    expect(box.scrollTop).toBe(1000);
  });

  it("shows running and completed agents and background tasks above the composer", async () => {
    const item = (overrides: Partial<BackgroundItem>): BackgroundItem => ({
      id: "a1",
      kind: "agent",
      name: "Explore",
      description: "Find DOIs",
      status: "running",
      started_at: "2026-10-06T09:00:00Z",
      finished_at: null,
      ...overrides,
    });
    const { user, push } = await openChat();
    expect(screen.queryByRole("button", { name: /running ·/ })).not.toBeInTheDocument();

    push({
      id: 2,
      session_id: "s1",
      type: "session.agents",
      payload: {
        agents: [agent({ status: "done" })] as never,
        background: {
          running: 2,
          completed: 2,
          items: [
            item({}),
            item({
              id: "b1",
              kind: "bash",
              name: "npm run dev",
              description: null,
              started_at: null,
            }),
            item({ id: "a2", name: "Plan", status: "done", description: null }),
            item({ id: "b2", kind: "bash", name: "make test", status: "failed" }),
          ],
        } as never,
      },
    });
    const bar = screen.getByRole("button", { name: "2 running · 2 completed" });
    expect(bar).toHaveAttribute("aria-expanded", "false");
    expect(bar.querySelector(".ff")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Agents, 0 active" })).toBeInTheDocument();
    // Between the transcript and the composer.
    const composer = defined(screen.getByLabelText("Message").closest(".comp"));
    expect(composer.previousElementSibling).toContainElement(bar);

    await user.click(bar);
    const running = screen.getByRole("list", { name: "Running" });
    const completed = screen.getByRole("list", { name: "Completed" });
    expect(
      within(running)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([expect.stringContaining("ExploreFind DOIs"), "npm run devRunning"]);
    // Running tasks show fireflies, finished ones their dot (B80).
    for (const li of within(running).getAllByRole("listitem")) {
      expect(li.firstElementChild).toHaveClass("ff");
    }
    for (const li of within(completed).getAllByRole("listitem")) {
      expect(li.firstElementChild).toHaveClass("dot");
    }
    expect(within(completed).getByText("Done")).toBeInTheDocument();
    expect(within(completed).getByText("Failed")).toBeInTheDocument();
    await user.click(bar);
    expect(screen.queryByRole("list", { name: "Running" })).not.toBeInTheDocument();

    push({
      id: 3,
      session_id: "s1",
      type: "session.agents",
      payload: {
        agents: [],
        background: { running: 0, completed: 1, items: [item({ status: "done" })] } as never,
      },
    });
    const idle = screen.getByRole("button", { name: "0 running · 1 completed" });
    expect(idle.querySelector(".ff")).toBeNull();
    expect(idle.querySelector(".dot.s-done")).not.toBeNull();
    await user.click(idle);
    expect(screen.queryByRole("list", { name: "Running" })).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Completed" })).toBeInTheDocument();
  });

  it("brings the background bar and the goals back collapsed", async () => {
    const { user, push } = await openChat();
    const item: BackgroundItem = {
      id: "t1",
      kind: "agent",
      name: "Explore",
      description: "Look around",
      status: "running",
      started_at: "2026-10-06T10:00:00Z",
      finished_at: null,
    };
    const background = (items: BackgroundItem[]) => {
      push({
        id: null,
        session_id: "s1",
        type: "session.agents",
        payload: {
          agents: [],
          background: { running: items.length, completed: 0, items } as never,
        },
      });
    };
    const tasks = (list: unknown[]) => {
      push({
        id: null,
        session_id: "s1",
        type: "session.tasks",
        payload: { tasks: list as never },
      });
    };
    const step = { id: "1", subject: "Read", description: null, active_form: null };

    background([item]);
    await user.click(screen.getByRole("button", { name: "1 running task" }));
    tasks([{ ...step, status: "in_progress" }]);
    await user.click(screen.getByRole("button", { name: /Now: Read/ }));
    background([]);
    tasks([]);
    background([item]);
    tasks([{ ...step, status: "pending" }]);

    expect(screen.getByRole("button", { name: "1 running task" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByRole("button", { name: /Now: Read/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("expands goals from the task list", async () => {
    const { user, push } = await openChat();
    const task = (
      id: string,
      subject: string,
      status: string,
      active_form: string | null = null,
    ) => ({
      id,
      subject,
      description: null,
      active_form,
      status,
    });

    push({
      id: 2,
      session_id: "s1",
      type: "session.tasks",
      payload: {
        tasks: [
          task("1", "Read", "completed"),
          task("2", "Install zod", "in_progress", "Installing zod"),
          task("3", "Write schema", "pending"),
          task("4", "Gone", "deleted"),
        ],
      },
    });
    const strip = screen.getByRole("button", { name: /Now: Install zod/ });
    expect(strip).toHaveTextContent("1 of 3");
    await user.click(strip);
    // The project's Goals behind the chat show the same steps (B47).
    const list = within(defined(document.getElementById("goals-list")));
    expect(list.getByText("Installing zod")).toBeInTheDocument();
    // The step in progress shows the working fireflies in its box (B80).
    expect(
      list.getByText("Installing zod").closest("li")?.querySelector(".cki .ff"),
    ).not.toBeNull();
    expect(list.getByText("done:").closest("li")?.querySelector(".ff")).toBeNull();
    expect(list.getByText("done:")).toBeInTheDocument();
    expect(list.getByText("pending:")).toBeInTheDocument();

    push({
      id: 3,
      session_id: "s1",
      type: "session.tasks",
      payload: { tasks: [task("1", "Read", "pending")] },
    });
    expect(screen.getByRole("button", { name: /Now: Read/ })).toBeInTheDocument();
    push({
      id: 4,
      session_id: "s1",
      type: "session.tasks",
      payload: { tasks: [task("1", "Plan", "in_progress")] },
    });
    expect(
      within(defined(document.getElementById("goals-list"))).getByText("Plan", { selector: ".x" }),
    ).toBeInTheDocument();
    push({
      id: 5,
      session_id: "s1",
      type: "session.tasks",
      payload: { tasks: [task("1", "Read", "completed")] },
    });
    expect(screen.getByRole("button", { name: /All done/ })).toBeInTheDocument();
  });

  it("lists agents with their last steps", async () => {
    const steps = Array.from({ length: 6 }, (_, i) => ({
      id: `x${String(i)}`,
      tool: i === 0 ? "Bash" : "Read",
      arg: `file${String(i)}`,
      result: i === 5 ? null : "ok",
    }));
    const { user } = await openChat({
      agents: [
        agent({ steps }),
        agent({
          id: "e",
          name: "Explore",
          status: "done",
          activity: null,
          description: "Find DOIs",
        }),
        agent({ id: "f", name: "Broken", status: "failed", activity: null, started_at: null }),
        agent({ id: "g", name: "Fresh", started_at: null, activity: null }),
      ],
    });

    await user.click(screen.getByRole("button", { name: "Agents, 2 active" }));
    const sheet = screen.getByRole("dialog", { name: "Agents" });
    expect(within(sheet).getByText("Find DOIs")).toBeInTheDocument();
    // A running agent shows fireflies, any other its dot (B80).
    expect(within(sheet).getByRole("button", { name: /main/ }).firstElementChild).toHaveClass("ff");
    expect(within(sheet).getByRole("button", { name: /Broken/ }).firstElementChild).toHaveClass(
      "dot s-fail",
    );
    expect(within(sheet).getByText("failed")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: /main/ }));
    const log = within(sheet).getByRole("list", { name: "Last steps" });
    expect(within(log).getAllByRole("listitem")).toHaveLength(5);
    expect(within(log).queryByText("file0")).not.toBeInTheDocument();
    expect(within(log).getByText("running").closest("li")?.querySelector(".ff")).not.toBeNull();
    await user.click(within(sheet).getByRole("button", { name: /main/ }));
    expect(within(sheet).queryByRole("list")).not.toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: /Fresh/ }));
    expect(within(sheet).getByText("No steps yet")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says when no agent has run", async () => {
    const { user } = await openChat();
    await user.click(screen.getByRole("button", { name: "Agents, 0 active" }));
    expect(screen.getByText("No agents have run yet.")).toBeInTheDocument();
  });

  it("goes back when the chat is archived from its actions, or deleted elsewhere", async () => {
    const { user, push } = await openChat();

    await user.click(screen.getByRole("button", { name: "Chat actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Archive" }));
    expect(await screen.findByRole("heading", { name: "Projects" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Archived/ }));
    await user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));
    await screen.findByRole("region", { name: "Validate contact form" });
    push({ id: 9, type: "session.deleted", session_id: null, payload: { session_id: "s1" } });
    expect(await screen.findByRole("heading", { name: "Projects" })).toBeInTheDocument();
  });

  it("goes back with Escape", async () => {
    const { user } = await openChat();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: "Validate contact form" })).not.toBeInTheDocument();
  });

  it("toasts when the chat cannot load", async () => {
    const api = fakeApi();
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [session()]));
    api.session.mockRejectedValue(new ApiError(404, "unknown session"));
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));

    expect(await screen.findByText("unknown session")).toBeInTheDocument();
  });
});

describe("inline approvals", () => {
  const created = (a: Approval, id: number) =>
    event({ id, type: "approval.created", payload: { approval: { ...a } } });

  it("approve or reject a permission in place", async () => {
    const items = [approval(), approval({ id: "q8" })];
    const { user, api } = await openChat({
      chat: session({ state: "waiting" }),
      approvals: items,
      events: [created(defined(items[0]), 1), created(defined(items[1]), 2)],
    });
    const [first, second] = screen.getAllByRole("group", { name: "Permission needed" });

    await user.click(within(defined(first)).getByRole("button", { name: "Approve" }));
    await user.click(within(defined(second)).getByRole("button", { name: "Reject" }));

    expect(api.resolveApproval.mock.calls).toEqual([
      ["q1", { behavior: "allow", always: false }],
      ["q8", { behavior: "deny", always: false }],
    ]);
  });

  it("always allow a permission in place, by Claude Code's suggested rule", async () => {
    const ruled = approval({
      payload: {
        tool: "Bash",
        input: { command: "npm test -- --run" },
        always_rule: "Bash(npm test:*)",
      },
    });
    const plain = approval({
      id: "q8",
      payload: { tool: "Read", input: { file_path: "/w/s1/a" } },
    });
    const { user, api } = await openChat({
      approvals: [ruled, plain],
      events: [created(ruled, 1), created(plain, 2)],
    });
    const [first, second] = screen.getAllByRole("group", { name: "Permission needed" });

    await user.click(
      within(defined(first)).getByRole("button", { name: "Always allow Bash(npm test:*)" }),
    );
    expect(await screen.findByText("Always allowed: Bash(npm test:*)")).toBeInTheDocument();
    await user.click(within(defined(second)).getByRole("button", { name: "Always allow Read" }));

    expect(api.resolveApproval.mock.calls).toEqual([
      ["q1", { behavior: "allow", always: true }],
      ["q8", { behavior: "allow", always: true }],
    ]);
    expect(await screen.findByText("Always allowed: Read")).toBeInTheDocument();
  });

  it("confirm the push address of a review from its sheet", async () => {
    const r = review();
    const { user, api } = await openChat({ approvals: [r], events: [created(r, 1)] });
    api.approve.mockRejectedValueOnce(
      new ApiError(409, "origin pushes to x", "remote_not_confirmed", {
        remote_urls: ["https://github.com/me/cv-page.git"],
        confirmed_url: null,
      }),
    );
    const sheet = await openReview(user);
    // Where it pushes shows in the sheet.
    expect(await within(sheet).findByText("Pushes to agent/contact")).toBeInTheDocument();

    await user.click(
      await enabled(within(sheet).getByRole("button", { name: "Approve and open PR" })),
    );
    const confirm = await screen.findByRole("alertdialog", { name: "Confirm the push address" });
    const pushThere = within(confirm).getByRole("button", { name: "Push there" });
    await waitFor(() => {
      expect(pushThere).toBeEnabled();
    });
    await user.click(pushThere);

    // The diff loaded after the refusal pins what the push publishes.
    expect(api.approve).toHaveBeenLastCalledWith("s1", {
      commit_message: "Validate contact form",
      expected_fingerprint: "f1ngerprint",
      expected_head: "c0ffee0000000000000000000000000000000000",
      confirm_remote_url: "https://github.com/me/cv-page.git",
    });
  });

  it("show why Claude Code asks for a permission", async () => {
    const asked = approval({
      payload: { tool: "Bash", input: { command: "ls /etc" }, reason: "Outside the project" },
    });
    await openChat({ approvals: [asked], events: [created(asked, 1)] });

    const box = screen.getByRole("group", { name: "Permission needed" });
    expect(within(box).getByText("Outside the project")).toBeInTheDocument();
  });

  it("answer a question in place", async () => {
    const q = question();
    const { user, api } = await openChat({ approvals: [q], events: [created(q, 1)] });

    const box = screen.getByRole("group", { name: "Question" });
    await user.click(within(box).getByRole("button", { name: "Send answer" }));

    expect(api.resolveApproval).toHaveBeenCalledWith("q2", { answers: { "DAG or tree?": "DAG" } });
  });

  it("answer a question in place with Other's text", async () => {
    const q = question();
    const { user, api } = await openChat({ approvals: [q], events: [created(q, 1)] });

    const box = within(screen.getByRole("group", { name: "Question" }));
    expect(box.queryByRole("textbox", { name: "Your answer" })).not.toBeInTheDocument();
    await user.click(box.getByRole("radio", { name: "Other" }));
    expect(box.getByRole("button", { name: "Send answer" })).toBeDisabled();
    await user.type(box.getByRole("textbox", { name: "Your answer" }), "Both");
    await user.click(box.getByRole("button", { name: "Send answer" }));

    expect(api.resolveApproval).toHaveBeenCalledWith("q2", { answers: { "DAG or tree?": "Both" } });
  });

  it("shows an answered question as the user's message under the question", async () => {
    const q = question();
    const { push } = await openChat({ approvals: [q], events: [created(q, 1)] });

    push({
      id: 2,
      session_id: "s1",
      type: "approval.resolved",
      payload: {
        approval: { ...q, status: "resolved", resolution: { answers: { "DAG or tree?": "Both" } } },
      },
    });

    const answer = await screen.findByText("Both");
    expect(answer.closest(".m-u")).not.toBeNull();
    expect(answer.closest(".m-ans")).toHaveTextContent("DAG or tree?");
    expect(screen.queryByText(/Answered:/)).not.toBeInTheDocument();
  });
});

describe("review bar", () => {
  const created = (a: Approval, id: number) =>
    event({ id, type: "approval.created", payload: { approval: { ...a } } });

  it("sits above the composer while a review is pending, not in the transcript", async () => {
    const r = review();
    await openChat({ approvals: [r], events: [created(r, 1)] });

    const bar = screen.getByRole("group", { name: "Changes to review" });
    expect(bar).toHaveTextContent("3 files changed");
    expect(within(bar).getByText("+48")).toBeInTheDocument();
    expect(within(bar).getByText("-19")).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Review" })).toBeInTheDocument();
    // Right above the message field.
    expect(bar.closest(".rvbw")?.nextElementSibling).toHaveClass("comp");
    expect(screen.queryByRole("group", { name: "Ready for review" })).not.toBeInTheDocument();
    expect(screen.queryByText("Raised contrast")).not.toBeInTheDocument();
  });

  it("names a single changed file", async () => {
    const r = review({ payload: { files: 1, additions: 2, deletions: 0, paths: ["a.css"] } });
    await openChat({ approvals: [r], events: [created(r, 1)] });

    expect(screen.getByRole("group", { name: "Changes to review" })).toHaveTextContent(
      "1 file changed",
    );
  });

  it("is hidden without a pending review", async () => {
    const p = approval();
    await openChat({ approvals: [p], events: [created(p, 1)] });

    expect(screen.queryByRole("group", { name: "Changes to review" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review" })).not.toBeInTheDocument();
  });

  it("opens the changes, approved from the sheet and never rejected", async () => {
    const r = review();
    const { user, api } = await openChat({ approvals: [r], events: [created(r, 1)] });

    let sheet = await openReview(user);
    await within(sheet).findByText("app/globals.css");
    expect(within(sheet).queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    sheet = await openReview(user);
    await user.click(
      await enabled(within(sheet).getByRole("button", { name: "Approve and open PR" })),
    );

    expect(api.approve).toHaveBeenCalledWith("s1", {
      commit_message: "Validate contact form",
      expected_fingerprint: "f1ngerprint",
      expected_head: "c0ffee0000000000000000000000000000000000",
    });
    // Approved: the bar and its sheet go.
    await waitFor(() => {
      expect(screen.queryByRole("group", { name: "Changes to review" })).not.toBeInTheDocument();
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });

  it("shows nothing for a superseded review", async () => {
    const r = review();
    const { push } = await openChat({ approvals: [r], events: [created(r, 1)] });

    push({
      id: 2,
      session_id: "s1",
      type: "approval.resolved",
      payload: { approval: { ...r, status: "superseded" } },
    });

    await waitFor(() => {
      expect(screen.queryByRole("group", { name: "Changes to review" })).not.toBeInTheDocument();
    });
    expect(screen.queryByText(/Approved|Rejected/)).not.toBeInTheDocument();
  });
});

describe("pull request", () => {
  const url = "https://github.com/me/cv-page/pull/7";

  it.each([
    [prStatus({ checks: [check("unit", "pending")] }), "ff", "#7, checks running"],
    [prStatus(), "s-rev", "#7, checks passed"],
    [prStatus({ checks: [check("unit", "failure")] }), "s-fail", "#7, checks failed"],
    [prStatus({ checks: [] }), "s-idle", "#7, no checks"],
    [prStatus({ state: "merged" }), "s-done", "#7, merged"],
    [null, "s-idle", "#7, status not read yet"],
  ])("shows a chip with the checks state %#", async (pr, tone, label) => {
    await openChat({ chat: session({ pr_url: url, pr }) });

    const chip = screen.getByRole("link", { name: `Pull request ${label}` });
    expect(chip).toHaveAttribute("href", url);
    expect(chip).toHaveAttribute("target", "_blank");
    // Running checks show the fireflies; any other state its dot (B80).
    expect(chip.firstElementChild).toHaveClass(tone);
  });

  it("has no chip without a pull request", async () => {
    await openChat();

    expect(screen.queryByRole("link", { name: /Pull request/ })).not.toBeInTheDocument();
  });

  it("updates the chip from session.pr events", async () => {
    const { push } = await openChat({ chat: session({ pr_url: url }) });

    push({
      id: 3,
      session_id: "s1",
      type: "session.pr",
      payload: { pr: prStatus({ checks: [check("unit", "failure")] }) as never },
    });

    expect(
      await screen.findByRole("link", { name: "Pull request #7, checks failed" }),
    ).toBeInTheDocument();
  });

  it("merges in place", async () => {
    const m = mergeApproval();
    const { user, api } = await openChat({
      chat: session({ pr_url: url, pr: prStatus() }),
      approvals: [m],
      events: [event({ id: 1, type: "approval.created", payload: { approval: { ...m } } })],
    });
    const box = screen.getByRole("group", { name: "Ready to merge" });

    expect(within(box).getByText("Ready to merge #7")).toBeInTheDocument();
    expect(within(box).getByRole("link", { name: "Open on GitHub" })).toHaveAttribute("href", url);
    await user.click(within(box).getByRole("button", { name: "Merge (squash)" }));

    expect(api.merge).toHaveBeenCalledWith("s1", { method: "squash" });
  });
});

describe("composer", () => {
  it("sends a message with attachments", async () => {
    const { user, api } = await openChat();
    api.uploadAttachment
      .mockResolvedValueOnce({
        id: "a1",
        filename: "shot.png",
        media_type: "image/png",
        size: 3,
        created_at: "x",
      })
      .mockRejectedValueOnce(new ApiError(413, "attachments larger than 20 MB are not accepted"))
      .mockResolvedValueOnce({
        id: "a2",
        filename: "notes.txt",
        media_type: "text/plain",
        size: 3,
        created_at: "x",
      });
    const files = screen.getByLabelText("Attach files");

    await user.click(screen.getByRole("button", { name: "Attach" }));
    await user.upload(files, [new File(["x"], "shot.png"), new File(["x"], "big.mov")]);
    expect(
      await screen.findByText("attachments larger than 20 MB are not accepted"),
    ).toBeInTheDocument();
    fireEvent.change(files, { target: { files: null } });
    await user.upload(files, new File(["x"], "notes.txt"));
    await user.click(await screen.findByRole("button", { name: "Remove notes.txt" }));
    const field = screen.getByLabelText("Message");
    await user.type(field, "Use this screenshot");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(api.sendMessage).toHaveBeenCalledWith("s1", "Use this screenshot", ["a1"]);
    await waitFor(() => {
      expect(field).toHaveValue("");
    });
    expect(screen.queryByText("shot.png")).not.toBeInTheDocument();
  });

  it("sends with Enter, keeps Shift+Enter for new lines and keeps text on failure", async () => {
    const { user, api } = await openChat();
    api.sendMessage.mockRejectedValueOnce(new ApiError(409, "session s1 is busy"));
    const field = screen.getByLabelText("Message");

    await user.type(field, "{Enter}");
    expect(api.sendMessage).not.toHaveBeenCalled();
    await user.type(field, "one{Shift>}{Enter}{/Shift}two{Enter}");
    expect(await screen.findByText("session s1 is busy")).toBeInTheDocument();
    expect(field).toHaveValue("one\ntwo");
    await user.click(screen.getByRole("button", { name: "Dictate" }));
    expect(field).toHaveFocus();
  });

  it("keeps what was typed and attached while a message was being sent", async () => {
    const { user, api } = await openChat();
    let delivered: () => void = () => undefined;
    api.sendMessage.mockReturnValueOnce(
      new Promise((resolve) => {
        delivered = () => {
          resolve({ ...session({ state: "running" }), queued_message: null });
        };
      }),
    );
    api.uploadAttachment.mockResolvedValueOnce({
      id: "a1",
      filename: "late.png",
      media_type: "image/png",
      size: 3,
      created_at: "x",
    });
    const field = screen.getByLabelText("Message");

    await user.type(field, "First part");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await user.type(field, " and a follow-up");
    await user.upload(screen.getByLabelText("Attach files"), new File(["x"], "late.png"));
    await screen.findByText("late.png");
    await act(async () => {
      delivered();
      await Promise.resolve();
    });

    expect(api.sendMessage).toHaveBeenCalledWith("s1", "First part", []);
    await waitFor(() => {
      expect(field).toHaveValue("and a follow-up");
    });
    expect(screen.getByText("late.png")).toBeInTheDocument();
  });

  it("adds a line with Return on a touch screen, where the Send button sends", async () => {
    // No fine pointer and no hover: a phone without a trackpad or mouse.
    vi.stubGlobal("matchMedia", () => fixedMedia(false));
    try {
      const { user, api } = await openChat();
      const field = screen.getByLabelText("Message");

      await user.type(field, "one{Enter}two");
      expect(api.sendMessage).not.toHaveBeenCalled();
      expect(field).toHaveValue("one\ntwo");
      await user.click(screen.getByRole("button", { name: "Send" }));

      expect(api.sendMessage).toHaveBeenCalledWith("s1", "one\ntwo", []);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("sends with Enter when a mouse or trackpad is around", async () => {
    vi.stubGlobal("matchMedia", (query: string) => fixedMedia(query.includes("pointer: fine")));
    try {
      const { user, api } = await openChat();

      await user.type(screen.getByLabelText("Message"), "go{Enter}");

      expect(api.sendMessage).toHaveBeenCalledWith("s1", "go", []);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("says when Claude Code has the chat open, until a message goes through", async () => {
    const { user, api } = await openChat();
    api.sendMessage.mockRejectedValueOnce(
      new ApiError(409, "open elsewhere", "open_in_claude_code"),
    );
    const field = screen.getByLabelText("Message");
    const region = field.closest(".comp")?.querySelector('[aria-live="polite"]');
    expect(region).toBeEmptyDOMElement();

    await user.type(field, "Continue{Enter}");
    // Said in a live region that was already there, so VoiceOver reads it out.
    expect(
      (
        await screen.findByText("This chat is open in Claude Code right now. Close it there first.")
      ).closest('[aria-live="polite"]'),
    ).toBe(region);
    expect(screen.queryByText("open elsewhere")).not.toBeInTheDocument();
    expect(field).toHaveValue("Continue");

    await user.type(field, "{Enter}");
    await waitFor(() => {
      expect(field).toHaveValue("");
    });
    expect(screen.queryByText(/open in Claude Code right now/)).not.toBeInTheDocument();
  });

  it("interrupts a running chat", async () => {
    const { user, api } = await openChat({ chat: session({ state: "running" }) });
    api.interrupt.mockRejectedValueOnce(new ApiError(409, "no turn in progress"));

    await user.click(screen.getByRole("button", { name: "Interrupt" }));
    expect(await screen.findByText("no turn in progress")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Interrupt" }));

    expect(api.interrupt).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Interrupted")).toBeInTheDocument();
  });

  it("changes the model, thinking and permission mode of an open chat", async () => {
    const { user, api } = await openChat({ chat: session({ model: "claude-x", effort: "high" }) });

    await user.click(screen.getByRole("button", { name: "Thinking: High" }));
    const thinking = screen.getByRole("dialog", { name: "Thinking" });
    expect(within(thinking).queryByRole("menuitemradio", { name: /Default/ })).toBeNull();
    // A model the list does not know offers every level.
    expect(within(thinking).getAllByRole("menuitemradio")).toHaveLength(5);
    await user.click(within(thinking).getByRole("menuitemradio", { name: /Max/ }));
    expect(screen.getByRole("button", { name: "Thinking: Max" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Model: claude-x" }));
    const sheet = screen.getByRole("dialog", { name: "Model" });
    expect(within(sheet).queryByRole("menuitemradio", { name: /agent default/ })).toBeNull();
    await user.click(within(sheet).getByRole("menuitemradio", { name: /^Opus 5.5/ }));
    expect(screen.getByRole("button", { name: "Model: Opus 5.5" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Permission mode: Ask" }));
    expect(screen.getByRole("menuitemradio", { name: /Ask/ })).toHaveFocus();
    await user.click(screen.getByRole("menuitemradio", { name: /Plan/ }));

    expect(api.updateSession.mock.calls).toEqual([
      ["s1", { effort: "max" }],
      ["s1", { model: "opus" }],
      ["s1", { permission_mode: "plan" }],
    ]);
  });

  it("is disabled in a closed chat", async () => {
    await openChat({ chat: session({ state: "closed" }) });

    expect(screen.getByLabelText("Message")).toBeDisabled();
    expect(screen.getByPlaceholderText("This chat is closed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("starts a new chat with the chosen model, thinking and mode", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("cv-page")]);
    api.createSession.mockResolvedValueOnce(null as never);
    api.createSession.mockRejectedValueOnce(new ApiError(422, "repo is dirty"));
    api.createSession.mockResolvedValueOnce(session({ id: "new", title: "Add tests" }));
    api.session.mockResolvedValue(detail({ id: "new", title: "Add tests" }));
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));
    const pick = async (selector: string, option: RegExp) => {
      await user.click(screen.getByRole("button", { name: selector }));
      await user.click(screen.getByRole("menuitemradio", { name: option }));
    };

    expect(screen.getByRole("button", { name: "Back to cv-page" })).toHaveFocus();
    await pick("Model: Model", /^Opus 5.5/);
    await pick("Thinking: Thinking", /Extra high/);
    await pick("Permission mode: Mode", /Accept edits/);
    await pick("Permission mode: Accept edits", /Default/);
    await pick("Permission mode: Mode", /Accept edits/);
    await user.click(screen.getByRole("button", { name: "Thinking: Extra high" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    const field = screen.getByLabelText("Message");
    await user.type(field, "Add tests{Enter}");
    await user.type(field, "{Enter}");
    expect(await screen.findByText("repo is dirty")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(api.createSession).toHaveBeenLastCalledWith({
      repo: "cv-page",
      prompt: "Add tests",
      attachment_ids: [],
      model: "opus",
      effort: "xhigh",
      permission_mode: "acceptEdits",
      // The project's default, from the folder's current branch (B55).
      mode: "worktree",
      base: "main",
    });
    expect(await screen.findByRole("region", { name: "Add tests" })).toBeInTheDocument();
  });

  it("moves text typed while the new chat is created into its composer", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("cv-page")]);
    let finish: (created: Session) => void = () => undefined;
    api.createSession.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    api.session.mockResolvedValue(detail({ id: "new", title: "Add tests" }));
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));

    await user.type(screen.getByLabelText("Message"), "Add tests{Enter}");
    await user.type(screen.getByLabelText("Message"), " and also the tests");
    await act(async () => {
      finish(session({ id: "new", title: "Add tests" }));
      await Promise.resolve();
    });

    await screen.findByRole("region", { name: "Add tests" });
    expect(screen.getByLabelText("Message")).toHaveValue("and also the tests");
    await user.click(screen.getByRole("button", { name: "Back to cv-page" }));
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));
    expect(screen.getByLabelText("Message")).toHaveValue("");
  });

  it("starts a new chat with the agent defaults", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("cv-page")]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));

    await user.type(screen.getByLabelText("Message"), "Go{Enter}");

    expect(api.createSession).toHaveBeenCalledWith({
      repo: "cv-page",
      prompt: "Go",
      attachment_ids: [],
      mode: "worktree",
      base: "main",
    });
    act(() => undefined);
  });
});
