import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { BackgroundSummary, JsonObject, NestEvent, Session } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { detail, event, pixie, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const tester = pixie({ id: "p1", slug: "tester", name: "Tester" });

interface Options {
  chat?: Session;
  background?: BackgroundSummary;
  api?: FakeApi;
}

async function openChat(
  events: NestEvent[],
  { chat = session({ state: "running" }), background, api = fakeApi() }: Options = {},
) {
  api.pixies.mockResolvedValue([tester]);
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail({ ...chat, ...(background ? { background } : {}) }));
  api.sessionEvents.mockResolvedValue(events);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  return rendered;
}

const message = (id: number, parent: string | null, ...blocks: JsonObject[]) =>
  event({ id, type: "session.message", payload: { parent_tool_use_id: parent, blocks } });
const live = (type: string, text: string, parent: string | null = null) => ({
  id: null,
  session_id: "s1",
  type,
  payload: { text, parent_tool_use_id: parent },
});
const agentCall = (id: string, subagent = "Explore") => ({
  type: "tool_use",
  id,
  name: "Agent",
  input: { description: "Find call sites", subagent_type: subagent },
});
const started = [
  event({ id: 1, type: "session.user_message", payload: { text: "Go" } }),
  event({ id: 2, type: "session.state", payload: { state: "running", turn_start: true } }),
];

describe("tool output (B59)", () => {
  it("shows the first lines of long output, and all of it on request", async () => {
    const output = Array.from({ length: 40 }, (_, i) => `line ${String(i + 1)}`).join("\n");
    const { user } = await openChat(
      [
        message(1, null, { type: "tool_use", id: "b1", name: "Bash", input: { command: "ls" } }),
        message(2, null, { type: "tool_result", tool_use_id: "b1", content: output }),
      ],
      { chat: session() },
    );
    const row = defined((await screen.findByText("40 lines")).closest("details"));
    await user.click(within(row).getByText("ls"));
    const pre = defined(row.querySelector("pre"));
    expect(pre).toHaveTextContent("line 8");
    expect(pre).not.toHaveTextContent("line 9");

    await user.click(within(row).getByRole("button", { name: "Show all 40 lines" }));
    expect(pre).toHaveTextContent("line 40");
    await user.click(within(row).getByRole("button", { name: "Show less" }));
    expect(pre).not.toHaveTextContent("line 9");
  });

  it("offers more of a single long line, and nothing more for short output", async () => {
    await openChat(
      [
        message(
          1,
          null,
          { type: "tool_use", id: "b1", name: "Bash", input: { command: "cat min.js" } },
          { type: "tool_use", id: "b2", name: "Bash", input: { command: "pwd" } },
        ),
        message(
          2,
          null,
          { type: "tool_result", tool_use_id: "b1", content: "x".repeat(5000) },
          { type: "tool_result", tool_use_id: "b2", content: "/w\n/x" },
        ),
      ],
      { chat: session() },
    );
    expect(await screen.findByRole("button", { name: "Show all" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Show all/ })).toHaveLength(1);
  });
});

describe("streamed thinking (B59)", () => {
  it("shows the thinking text as it streams, folded under the live line", async () => {
    const { push } = await openChat(started);
    push({ id: null, session_id: "s1", type: "session.thinking", payload: { active: true } });
    expect(screen.getByText(/^Thinking\.\.\./).closest("details")).toBeNull();

    push(live("session.thinking_delta", "Let me check "));
    push(live("session.thinking_delta", "the failing test"));
    const block = defined(screen.getByText(/^Thinking\.\.\./).closest("details"));
    expect(block).not.toHaveAttribute("open");
    expect(within(block).getByText("Let me check the failing test")).toBeInTheDocument();

    push(
      message(3, null, {
        type: "thinking",
        text: "Let me check the failing test.",
        duration_ms: 4000,
      }),
    );
    expect(screen.getByText("Thought for 4s")).toBeInTheDocument();
    expect(screen.queryByText("Let me check the failing test")).not.toBeInTheDocument();
  });
});

describe("subagents in the chat (B59)", () => {
  it("shows a subagent's thinking, text and tools in its call's row, streaming", async () => {
    const { user, push } = await openChat([
      ...started,
      message(3, null, agentCall("a1")),
      message(4, "a1", { type: "thinking", text: "The tests import it", duration_ms: null }),
      message(5, "a1", { type: "tool_use", id: "s1", name: "Grep", input: { pattern: "helper" } }),
    ]);
    const row = defined((await screen.findByText("Find call sites")).closest("details"));
    await user.click(within(row).getByText("Find call sites"));
    expect(within(row).getByText("The tests import it")).toHaveClass("pxthink");
    expect(within(row).getByText("Grep helper")).toHaveClass("pxstep");

    push(live("session.subagent_delta", "Found 3 ", "a1"));
    push(live("session.subagent_delta", "call sites", "a1"));
    push(live("session.delta", "Main text"));
    expect(within(row).getByText("Found 3 call sites")).toHaveClass("pxtext", "live");
    expect(within(row).queryByText("Main text")).not.toBeInTheDocument();

    push(message(6, "a1", { type: "text", text: "Found 3 call sites." }));
    expect(within(row).queryByText("Found 3 call sites")).not.toBeInTheDocument();
    expect(within(row).getByText("Found 3 call sites.")).toHaveClass("pxtext");
  });

  it("opens a running subagent's row once it streams, before any message", async () => {
    const { push } = await openChat([...started, message(3, null, agentCall("a1"))]);
    expect((await screen.findByText("Find call sites")).closest("details")).toBeNull();
    push(live("session.subagent_delta", "Looking", "a1"));
    expect(screen.getByText("Find call sites").closest("details")).not.toBeNull();
  });

  it("stops one running subagent from its row", async () => {
    const api = fakeApi();
    const { user, push } = await openChat([...started, message(3, null, agentCall("a1"))], { api });

    const stop = await screen.findByRole("button", { name: "Stop Find call sites" });
    await user.click(stop);
    expect(api.stopTask).toHaveBeenCalledWith("s1", "a1");
    expect(stop).toBeDisabled();
    // Its row stays as it was: the button never opens it.
    expect(screen.getByText("Find call sites").closest("details")).toBeNull();

    push(message(4, null, { type: "tool_result", tool_use_id: "a1", content: "Stopped" }));
    expect(screen.queryByRole("button", { name: "Stop Find call sites" })).not.toBeInTheDocument();
  });

  it("hides the stop once the run is closed, and offers it again for a finished task", async () => {
    const api = fakeApi();
    api.stopTask
      .mockRejectedValueOnce(new ApiError(404, "session 's1' has no running task 'a1'"))
      .mockRejectedValueOnce(new ApiError(409, "session 's1' has no agent running"));
    const { user } = await openChat([...started, message(3, null, agentCall("a1"))], { api });

    const stop = await screen.findByRole("button", { name: "Stop Find call sites" });
    await user.click(stop);
    await waitFor(() => {
      expect(stop).toBeEnabled();
    });
    await user.click(stop);
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "Stop Find call sites" }),
      ).not.toBeInTheDocument();
    });
  });

  it("stops a pixie's call and shows its thinking and streamed text", async () => {
    const api = fakeApi();
    const { user, push } = await openChat(
      [
        ...started,
        message(3, null, agentCall("a1", "tester")),
        message(4, "a1", { type: "thinking", text: "Checking the form" }),
      ],
      { api },
    );
    await user.click(await screen.findByRole("button", { name: /Find call sites/ }));
    const steps = screen.getByRole("group", { name: "Tester's steps" });
    expect(within(steps).getByText("Checking the form")).toHaveClass("pxthink");
    push(live("session.subagent_delta", "All fields", "a1"));
    expect(within(steps).getByText("All fields")).toHaveClass("live");

    await user.click(screen.getByRole("button", { name: "Stop Tester" }));
    expect(api.stopTask).toHaveBeenCalledWith("s1", "a1");
  });
});

describe("background tasks (B59)", () => {
  it("stops a running background command from the bar", async () => {
    const api = fakeApi();
    const background: BackgroundSummary = {
      running: 1,
      completed: 1,
      items: [
        {
          id: "b1",
          kind: "bash",
          name: "npm run dev",
          description: null,
          status: "running",
          started_at: null,
          finished_at: null,
        },
        {
          id: "b2",
          kind: "bash",
          name: "npm test",
          description: null,
          status: "done",
          started_at: null,
          finished_at: null,
        },
      ],
    };
    const { user } = await openChat(
      [
        ...started,
        message(
          3,
          null,
          {
            type: "tool_use",
            id: "b1",
            name: "Bash",
            input: { command: "npm run dev", run_in_background: true },
          },
          { type: "tool_use", id: "b2", name: "Bash", input: { command: "npm test" } },
        ),
      ],
      { api, background },
    );
    await user.click(await screen.findByRole("button", { name: "1 running task" }));
    expect(screen.queryByRole("button", { name: "Stop npm test" })).not.toBeInTheDocument();
    const stop = screen.getByRole("button", { name: "Stop npm run dev" });
    await user.click(stop);
    expect(api.stopTask).toHaveBeenCalledWith("s1", "b1");
    expect(stop).toBeDisabled();
  });
});

describe("hooks in the transcript (B59)", () => {
  const hook = (id: number, payload: JsonObject) =>
    event({
      id,
      type: "session.hook",
      payload: { hook_id: null, exit_code: 0, system_message: null, output: null, ...payload },
    });

  it("shows a hook's message, failure and output as quiet rows", async () => {
    const { user } = await openChat(
      [
        hook(1, {
          hook_name: "PostToolUse:Edit",
          outcome: "success",
          system_message: "Formatted 2 files",
        }),
        hook(2, {
          hook_name: "PreToolUse:Bash",
          outcome: "error",
          exit_code: 2,
          output: "Blocked: run the tests first",
        }),
        hook(3, { hook_name: "Stop", outcome: "cancelled", output: "lint ok" }),
        // Context for Claude, which Claude Code does not show either.
        hook(4, { hook_name: "UserPromptSubmit", outcome: "success", output: "[14:37 EEST]" }),
      ],
      { chat: session() },
    );

    expect(await screen.findByText("PostToolUse:Edit says: Formatted 2 files")).toHaveClass(
      "m-hook",
    );
    const failed = defined(screen.getByText("PreToolUse:Bash hook failed (exit 2)").parentElement);
    expect(failed).toHaveClass("m-hook", "bad");
    expect(within(failed).getByText("Blocked: run the tests first")).toBeVisible();
    const output = defined(screen.getByText("Stop hook output").closest("details"));
    expect(output).not.toHaveAttribute("open");
    await user.click(screen.getByText("Stop hook output"));
    expect(output).toHaveAttribute("open");
    expect(within(output).getByText("lint ok")).toBeInTheDocument();
    expect(screen.queryByText(/UserPromptSubmit/)).not.toBeInTheDocument();
  });
});
