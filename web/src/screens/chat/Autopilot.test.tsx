import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AutopilotEnd, JsonObject, NestEvent, Session, TrackedTask } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import {
  agentDefaults,
  autopilotDecision,
  autopilotReport,
  autopilotRun,
  detail,
  event,
  repo,
  session,
} from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";
import { stepLine } from "./useAutopilot.ts";

function task(overrides: Partial<TrackedTask>): TrackedTask {
  const fields = { id: "1", subject: "Task", description: null, active_form: null };
  return { ...fields, status: "pending", ...overrides };
}

async function openChat(chat: Session, events: NestEvent[] = [], tasks: TrackedTask[] = []) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("todo-ui")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail({ ...chat, tasks }));
  api.sessionEvents.mockResolvedValue(events);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  return { api, user: rendered.user };
}

const radio = (name: string) => screen.getByRole("radio", { name });

describe("Autopilot on a chat (B120)", () => {
  it("turns on with the budget chosen in the popover", async () => {
    const { api, user } = await openChat(session());

    await user.click(screen.getByRole("button", { name: "Autopilot: off" }));
    await user.click(radio("Time"));
    await user.click(radio("4 h"));
    await user.click(radio("70%"));
    expect(api.setAutopilot).not.toHaveBeenCalled();
    await user.click(screen.getByRole("switch", { name: "Autopilot" }));

    expect(api.setAutopilot).toHaveBeenCalledWith("s1", {
      on: true,
      stop_after_minutes: 240,
      weekly_cap: 70,
    });
  });

  it("runs until done by default", async () => {
    const { api, user } = await openChat(session());

    await user.click(screen.getByRole("button", { name: "Autopilot: off" }));
    await user.click(screen.getByRole("switch", { name: "Autopilot" }));

    expect(api.setAutopilot).toHaveBeenCalledWith("s1", {
      on: true,
      stop_after_minutes: null,
      weekly_cap: null,
    });
  });

  it("sends a change during a run again, and shows the run's budget", async () => {
    const run = autopilotRun({
      started_at: "2026-10-06T12:00:00Z",
      until: "2026-10-06T14:00:00Z",
      weekly_cap: 80,
    });
    const { api, user } = await openChat(
      session({ autopilot: run, permission_mode: "bypassPermissions" }),
    );

    await user.click(screen.getByRole("button", { name: "Autopilot: on" }));
    expect(radio("2 h")).toBeChecked();
    expect(radio("80%")).toBeChecked();
    await user.click(radio("Off"));

    expect(api.setAutopilot).toHaveBeenCalledWith("s1", {
      on: true,
      stop_after_minutes: 120,
      weekly_cap: null,
    });
  });

  it("keeps the mode control on Bypass and locked during a run", async () => {
    await openChat(session({ autopilot: autopilotRun(), permission_mode: "default" }));

    expect(screen.getByRole("button", { name: "Permission mode: Bypass" })).toBeDisabled();
  });

  it("shows the running bar with Turn off", async () => {
    const { api, user } = await openChat(session({ autopilot: autopilotRun() }));

    const bar = screen.getByRole("group", { name: "Autopilot" });
    await user.click(within(bar).getByRole("button", { name: "Turn off" }));

    expect(api.setAutopilot).toHaveBeenCalledWith("s1", { on: false });
  });

  it("shows the current step on the running bar, left out without one", async () => {
    const tasks = [
      task({ id: "1", subject: "Plan", status: "completed" }),
      task({ id: "2", subject: "Tests", active_form: "Writing tests", status: "in_progress" }),
      task({ id: "3", subject: "Ship" }),
    ];
    await openChat(session({ autopilot: autopilotRun() }), [], tasks);

    const bar = screen.getByRole("group", { name: "Autopilot" });
    expect(await within(bar).findByText("Step 2 of 3: Writing tests")).toBeInTheDocument();
    expect(stepLine([])).toBeNull();
    expect(stepLine([task({ status: "completed" })])).toBeNull();
  });

  it("shows a decision in the chat and opens it to its options and reason", async () => {
    const chat = session();
    const { user } = await openChat(chat, [
      event({
        id: 1,
        type: "session.autopilot_decision",
        payload: {
          decision: {
            kind: "question",
            title: "Which port?",
            answer: "8080",
            at: "2026-10-06T12:00:00Z",
            options: [
              { label: "3000", description: "The default", picked: false },
              { label: "8080", description: "Free here", picked: true },
            ],
            reason: "The agent recommended it: Free here",
            detail: null,
          },
        },
      }),
    ]);

    const line = await screen.findByText("Which port?");
    const summary = line.closest("summary");
    expect(summary).toHaveTextContent("Which port? 8080");
    expect(summary?.parentElement).not.toHaveAttribute("open");
    await user.click(line);

    expect(summary?.parentElement).toHaveAttribute("open");
    expect(screen.getByText("Free here")).toBeVisible();
    expect(screen.getByText("The agent recommended it: Free here")).toBeVisible();
  });

  it("starts a new chat on Autopilot in a worktree, the mode to go back to kept", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("todo-ui")]);
    api.sessions.mockResolvedValue([]);
    api.agentDefaults.mockResolvedValue(agentDefaults({ mode: "in_place" }));
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: "New chat in todo-ui" }));

    await user.click(screen.getByRole("button", { name: "Autopilot: off" }));
    await user.click(radio("80%"));
    await user.click(screen.getByRole("switch", { name: "Autopilot" }));
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(await screen.findByRole("button", { name: /New worktree$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Permission mode: Bypass" })).toBeDisabled();
    await user.type(screen.getByLabelText("Message"), "Fix it");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(api.createSession).toHaveBeenCalledWith(
      expect.objectContaining({
        autopilot: { on: true, stop_after_minutes: null, weekly_cap: 80 },
        mode: "worktree",
        permission_mode: agentDefaults().permission_mode,
      }),
    );
    expect(api.setAutopilot).not.toHaveBeenCalled();
  });

  it("keeps each run's report in the chat, with what it decided and no way to dismiss it", async () => {
    const report = (id: number, summary: string, ended: AutopilotEnd) =>
      event({
        id,
        type: "session.autopilot_report",
        payload: {
          report: autopilotReport({
            ended,
            summary,
            decisions: [
              autopilotDecision(),
              autopilotDecision({ kind: "denied", title: "git push", answer: "Denied" }),
            ],
          }) as unknown as JsonObject,
        },
      });
    await openChat(session(), [
      report(1, "Fixed the form.", "weekly_cap"),
      report(2, "Fixed the page.", "done"),
    ]);

    const [card, second] = await screen.findAllByRole("group", { name: "Autopilot report" });
    expect(second).toHaveTextContent("Fixed the page.");
    if (card === undefined) throw new Error("no report");
    expect(within(card).getByText("Weekly cap reached")).toBeInTheDocument();
    expect(within(card).getByText("Fixed the form.")).toBeInTheDocument();
    const decided = within(within(card).getByRole("list")).getAllByRole("listitem");
    expect(decided[0]).toHaveTextContent("Which port? 8080");
    expect(decided[1]).toHaveTextContent("git push Denied");
    expect(within(card).queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
  });
});
