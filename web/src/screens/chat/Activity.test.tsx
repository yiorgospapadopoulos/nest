import { act, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BackgroundSummary, HarnessEvent, JsonObject, Session } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { approval, detail, event, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";
import { BackgroundBar } from "./BackgroundBar.tsx";

// The turn below starts at 10:00:00; the clock reads 12 seconds later.
const START = "2026-10-06T10:00:00Z";

async function openChat(chat: Session, events: HarnessEvent[], background?: BackgroundSummary) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("todo-ui")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail({ ...chat, ...(background ? { background } : {}) }));
  api.sessionEvents.mockResolvedValue(events);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  return rendered;
}

const at = (id: number, type: string, payload: JsonObject, seconds = 0) =>
  event({ id, type, payload, ts: new Date(Date.parse(START) + seconds * 1000).toISOString() });
const blocks = (id: number, list: JsonObject[]) =>
  at(id, "session.message", { parent_tool_use_id: null, blocks: list });
const call = (id: string, name: string, input: JsonObject = {}) => ({
  type: "tool_use",
  id,
  name,
  input,
});
const result = (id: string, content = "ok", is_error = false) => ({
  type: "tool_result",
  tool_use_id: id,
  content,
  is_error,
});
const turnStarted = [
  at(1, "session.user_message", { text: "Fix it" }),
  at(2, "session.state", { state: "running", error: null, turn_start: true }),
];

afterEach(() => {
  vi.useRealTimers();
});

function fakeClock(seconds: number) {
  // Only the clock and the ticker: testing-library still waits with real timeouts.
  vi.useFakeTimers({
    now: Date.parse(START) + seconds * 1000,
    toFake: ["Date", "setInterval", "clearInterval"],
  });
}

describe("a running turn", () => {
  it("ticks a working timer and says when the agent thinks", async () => {
    fakeClock(12);
    const { push } = await openChat(session({ state: "running" }), turnStarted);

    expect(screen.getByText("Working... 12s")).toHaveClass("glow");
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByText("Working... 1m 12s")).toBeInTheDocument();

    push({
      id: null,
      session_id: "s1",
      type: "session.thinking",
      ts: START,
      payload: { active: true },
    });
    expect(screen.getByText("Thinking... 1m 12s")).toBeInTheDocument();
    push({
      id: null,
      session_id: "s1",
      type: "session.thinking",
      ts: START,
      payload: { active: false },
    });
    expect(screen.getByText("Working... 1m 12s")).toBeInTheDocument();

    push({
      id: 3,
      session_id: "s1",
      type: "session.state",
      ts: START,
      payload: { state: "idle", duration_ms: 72_000 },
    });
    expect(screen.queryByText(/Working/)).not.toBeInTheDocument();
    // Also announced, in the chat's status region.
    expect(screen.getByText("Worked for 1m 12s", { selector: ".tx *" })).toHaveClass("m-turn");
  });

  it("works without a time until the agent gets the message", async () => {
    await openChat(session({ state: "starting" }), [at(1, "session.state", { state: "starting" })]);

    expect(screen.getByText("Working...")).toBeInTheDocument();
  });

  it("sums up a run of tool calls and expands to the calls themselves", async () => {
    const { user, push } = await openChat(session({ state: "running" }), [
      ...turnStarted,
      blocks(3, [
        call("t1", "Bash", { command: "npm test" }),
        call("t2", "Read", { file_path: "/w/s1/a.ts" }),
        call("t3", "Bash", { command: "npm run lint" }),
      ]),
      blocks(4, [result("t2", "one\ntwo"), result("t3", "boom", true)]),
    ]);

    const summary = screen.getByText("Running 2 commands, reading 1 file");
    expect(summary).toHaveClass("glow");
    const group = defined(summary.closest("details"));
    expect(within(group).getByText("1 failed")).toHaveClass("tr bad");
    expect(group.open).toBe(false);
    await user.click(summary);
    expect(group.open).toBe(true);
    expect(within(group).getByText("npm test")).toBeInTheDocument();
    expect(within(group).getByText("2 lines")).toBeInTheDocument();

    push({
      id: 5,
      session_id: "s1",
      type: "session.message",
      ts: START,
      payload: { blocks: [result("t1")] },
    });
    expect(screen.getByText("Ran 2 commands, read 1 file")).not.toHaveClass("glow");
  });

  it("counts agents that are done, including background ones still running", async () => {
    const background: BackgroundSummary = {
      running: 1,
      completed: 0,
      items: [
        {
          id: "a3",
          kind: "agent",
          name: "Explore",
          description: null,
          status: "running",
          started_at: START,
          finished_at: null,
        },
      ],
    };
    await openChat(
      session({ state: "running" }),
      [
        ...turnStarted,
        blocks(3, [call("a1", "Agent"), call("a2", "Task"), call("a3", "Agent")]),
        blocks(4, [result("a2", "found it"), result("a3", "Started in the background")]),
      ],
      background,
    );

    expect(screen.getByText("Running 3 agents, 1 done")).toHaveClass("glow");
    expect(screen.getByRole("button", { name: "1 running task" })).toBeInTheDocument();
    expect(screen.getByText("1 running task")).toHaveClass("glow");
  });
});

describe("screen reader announcements", () => {
  // Whatever an assistive technology reads out as it changes.
  const liveRegion = (node: Element) =>
    node.closest(
      '[aria-live]:not([aria-live="off"]), [role="status"], [role="log"], [role="alert"]',
    );

  it("leave the ticking timer and streamed text out, and announce finished items only", async () => {
    fakeClock(12);
    const { push } = await openChat(session({ state: "running" }), [
      ...turnStarted,
      blocks(3, [{ type: "text", text: "Earlier answer" }]),
    ]);
    const chat = screen.getByRole("region", { name: "Validate contact form" });
    const announcer = within(chat).getByRole("status");
    // The history already on screen is not read out again.
    expect(announcer).toBeEmptyDOMElement();
    expect(liveRegion(screen.getByText("Working... 12s"))).toBeNull();
    expect(liveRegion(screen.getByText("Earlier answer"))).toBeNull();

    push({ id: null, session_id: "s1", type: "session.delta", payload: { text: "Strea" } });
    expect(liveRegion(screen.getByText("Strea"))).toBeNull();
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(announcer).toBeEmptyDOMElement();

    push({
      id: 4,
      session_id: "s1",
      type: "session.message",
      ts: START,
      payload: { blocks: [{ type: "text", text: "Streamed answer" }] },
    });
    expect(announcer).toHaveTextContent("Streamed answer");
    // A tool call after it is not worth reading out.
    push({
      id: 5,
      session_id: "s1",
      type: "session.message",
      ts: START,
      payload: { blocks: [call("t1", "Read")] },
    });
    expect(announcer).toHaveTextContent("Streamed answer");

    push({
      id: 6,
      session_id: "s1",
      type: "session.state",
      ts: START,
      payload: { state: "idle", duration_ms: 72_000 },
    });
    expect(announcer).toHaveTextContent("Worked for 1m 12s");
  });

  it("say when a chat needs approval, and not again what came before it", async () => {
    const { push } = await openChat(session({ state: "running" }), [
      ...turnStarted,
      blocks(3, [{ type: "text", text: "Asking first" }]),
    ]);
    const announcer = within(
      screen.getByRole("region", { name: "Validate contact form" }),
    ).getByRole("status");

    push({
      id: 4,
      session_id: "s1",
      type: "approval.created",
      payload: { approval: { ...approval() } },
    });
    expect(announcer).toHaveTextContent("Needs your approval");

    // Superseded: the request leaves the transcript, and the older answer is last again.
    push({
      id: 5,
      session_id: "s1",
      type: "approval.resolved",
      payload: { approval: { ...approval(), status: "superseded" } },
    });
    expect(screen.queryByText("npm install zod")).not.toBeInTheDocument();
    expect(announcer).toHaveTextContent("Needs your approval");
  });
});

describe("a finished turn", () => {
  it("shows thinking rows, plain calls and how long the turn worked", async () => {
    const { user } = await openChat(session({ state: "idle" }), [
      ...turnStarted,
      blocks(3, [
        { type: "thinking", text: "Check the form first", duration_ms: 8_000 },
        { type: "thinking", text: "", duration_ms: 3_000 },
        { type: "thinking", text: "No timing" },
        call("t1", "Read", { file_path: "/w/s1/a.ts" }),
        { type: "text", text: "All good." },
      ]),
      blocks(4, [result("t1")]),
      at(5, "session.state", { state: "idle", error: null, duration_ms: 72_000 }, 72),
    ]);

    const thought = screen.getByText("Thought for 8s");
    const row = defined(thought.closest("details"));
    expect(row).toHaveClass("think");
    expect(row.open).toBe(false);
    await user.click(thought);
    expect(row.open).toBe(true);
    expect(within(row).getByText("Check the form first")).toBeInTheDocument();
    // Left out by the engine: nothing to expand.
    expect(screen.getByText("Thought for 3s").closest("details")).toBeNull();
    expect(screen.getByText("Thought").closest("details")).not.toBeNull();
    expect(screen.getByText("Read").closest(".tool")).not.toHaveClass("tgroup");
    expect(screen.getByText("Worked for 1m 12s")).toBeInTheDocument();
    expect(screen.queryByText(/Working/)).not.toBeInTheDocument();
  });

  it("says how long a stopped turn ran", async () => {
    await openChat(session({ state: "interrupted" }), [
      ...turnStarted,
      at(3, "session.state", { state: "interrupted", error: null, duration_ms: 40_000 }, 40),
    ]);

    expect(screen.getByText("Stopped after 40s")).toBeInTheDocument();
    expect(screen.queryByText("Interrupted", { selector: ".m-sys" })).not.toBeInTheDocument();
  });
});

describe("the background bar", () => {
  const task = (id: string, status: "running" | "done", seconds: number) => ({
    id,
    kind: "agent" as const,
    name: "Explore",
    description: `Task ${id}`,
    status,
    started_at: new Date(Date.parse(START) + seconds * 1000).toISOString(),
    finished_at: status === "done" ? START : null,
  });

  it("counts only the tasks of the user's latest message, and earlier ones still running", async () => {
    // The first exchange finished four tasks and left one running; the second started three.
    const background: BackgroundSummary = {
      running: 3,
      completed: 5,
      items: [
        ...["e1", "e2", "e3", "e4"].map((id, index) => task(id, "done", 5 + index)),
        task("bg", "running", 9),
        task("n1", "done", 61),
        task("n2", "running", 62),
        task("n3", "running", 63),
      ],
    };
    const { user, push } = await openChat(
      session({ state: "running" }),
      [
        ...turnStarted,
        at(3, "session.state", { state: "idle", error: null }, 30),
        at(4, "session.user_message", { text: "Next" }, 60),
        at(5, "session.state", { state: "running", error: null, turn_start: true }, 60),
      ],
      background,
    );

    const bar = screen.getByRole("button", { name: "3 running · 1 completed" });
    await user.click(bar);
    const names = (list: string) =>
      within(screen.getByRole("list", { name: list }))
        .getAllByRole("listitem")
        .map((li) => li.querySelector(".mono")?.textContent);
    expect(names("Running")).toEqual(["Task bg", "Task n2", "Task n3"]);
    expect(names("Completed")).toEqual(["Task n1"]);

    // The next message starts from zero; the bar hides until one of its tasks starts.
    act(() => {
      push({
        id: 6,
        session_id: "s1",
        type: "session.user_message",
        ts: new Date(Date.parse(START) + 120_000).toISOString(),
        payload: { text: "And then" },
      });
      push({
        id: 7,
        session_id: "s1",
        type: "session.agents",
        payload: {
          agents: [],
          background: {
            ...background,
            running: 0,
            completed: 8,
            items: background.items.map((item) => ({ ...item, status: "done" })),
          },
        },
      });
    });
    expect(screen.queryByRole("button", { name: /running/ })).not.toBeInTheDocument();
  });
});

describe("background bar wording", () => {
  it("names running tasks alone until one completes, as on the Mac", () => {
    const item = (id: string, status: "running" | "done") => ({
      id,
      kind: "agent" as const,
      name: "Explore",
      description: null,
      status,
      started_at: START,
      finished_at: status === "done" ? START : null,
    });
    const { rerender } = render(
      <BackgroundBar
        summary={{ running: 2, completed: 0, items: [item("a", "running"), item("b", "running")] }}
      />,
    );
    expect(screen.getByRole("button", { name: "2 running tasks" })).toBeInTheDocument();

    rerender(
      <BackgroundBar
        summary={{ running: 1, completed: 1, items: [item("a", "running"), item("b", "done")] }}
      />,
    );
    expect(screen.getByRole("button", { name: "1 running · 1 completed" })).toBeInTheDocument();
  });
});
