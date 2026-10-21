import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { Goal, JsonValue, Session, TrackedTask } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { approval, detail, repo, session, task } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const PLAN: TrackedTask[] = [
  task({ id: "1", subject: "Read the form", status: "completed" }),
  task({ id: "2", subject: "Add checks", active_form: "Adding checks", status: "in_progress" }),
  task({ id: "3", subject: "Write tests" }),
  task({ id: "4", subject: "Dropped idea", status: "deleted" }),
];

const WORKING = session({
  id: "w",
  title: "Fix the header",
  state: "running",
  updated_at: "2026-10-01T00:00:00Z",
});
const FINISHED = session({ id: "f", title: "Tidy styles", updated_at: "2026-10-05T00:00:00Z" });
const QUIET = session({ id: "q", title: "Old question" });

function withGoals(chats: Session[], goals: Goal[], repos = ["cv-page"]): FakeApi {
  const api = fakeApi();
  api.repos.mockResolvedValue(repos.map(repo));
  api.sessions.mockImplementation((archived) =>
    Promise.resolve(chats.filter((s) => (s.archived_at !== null) === archived)),
  );
  api.session.mockImplementation((id) =>
    Promise.resolve(
      detail({
        ...chats.find((s) => s.id === id),
        tasks: goals.find((g) => g.session_id === id)?.tasks ?? [],
      }),
    ),
  );
  api.goals.mockResolvedValue(goals);
  return api;
}

// Needs you is the tab the app opens on.
const openNeedsYou = (api: FakeApi) => renderApp({ api });

const goalsRegion = () => screen.getByRole("region", { name: "Goals" });
const goal = (title: string) =>
  within(goalsRegion()).getByRole("article", { name: new RegExp(`^${title}:`) });
const steps = (title: string) =>
  within(goalsRegion()).getByRole("list", { name: `Steps of ${title}` });

describe("the project's goals under Needs you (B47, B102 item 11)", () => {
  it("shows each chat's progress with a thin bar, its steps open, working chats first", async () => {
    const api = withGoals(
      [FINISHED, WORKING, QUIET],
      [
        { session_id: "w", tasks: [] },
        { session_id: "f", tasks: PLAN },
      ],
    );
    api.approvals.mockResolvedValue([approval({ session_id: "q" })]);
    await openNeedsYou(api);

    await screen.findByRole("region", { name: "Goals" });
    expect(api.goals).toHaveBeenCalledWith("cv-page");
    expect(within(goalsRegion()).getByRole("heading", { level: 2 })).toHaveTextContent("Goals2");
    expect(
      within(goalsRegion())
        .getAllByRole("article")
        .map((a) => a.getAttribute("aria-label")),
    ).toEqual(["Fix the header: No plan yet, Running", "Tidy styles: 1 of 3, Idle"]);
    // Under the Needs you list, as the Mac's right panel.
    const needs = screen.getByRole("article", { name: "Permission: Validate contact form" });
    expect(
      needs.compareDocumentPosition(goalsRegion()) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // A running chat's goal shows fireflies, any other its dot (B80).
    expect(goal("Fix the header").querySelector(".nrow")?.firstElementChild).toHaveClass("ff");
    expect(goal("Fix the header")).toHaveTextContent("No plan yet");
    expect(goal("Tidy styles").querySelector(".nrow")?.firstElementChild).toHaveClass("dot s-idle");
    expect(goal("Tidy styles")).toHaveTextContent("1 of 3");
    const bar = defined(goal("Tidy styles").querySelector<HTMLElement>(".gbar"));
    expect(bar.style.getPropertyValue("--done")).toBe("33%");
    expect(goal("Fix the header").querySelector(".gbar")).toBeNull();

    const items = within(steps("Tidy styles")).getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual([
      "1done: Read the form",
      "2in progress: Add checksAdding checks",
      "3pending: Write tests",
    ]);
    expect(within(goalsRegion()).queryByText("Old question")).not.toBeInTheDocument();
  });

  it("folds a goal's steps from its chevron or a tap on its row", async () => {
    const api = withGoals([FINISHED], [{ session_id: "f", tasks: PLAN }]);
    const { user } = await openNeedsYou(api);
    await screen.findByRole("region", { name: "Goals" });

    const chevron = within(goal("Tidy styles")).getByRole("button", { name: "Hide details" });
    expect(chevron).toHaveAttribute("aria-expanded", "true");
    await user.click(chevron);
    expect(within(goalsRegion()).queryByRole("list")).not.toBeInTheDocument();
    expect(chevron).toHaveAccessibleName("Show details");

    await user.click(defined(goal("Tidy styles").querySelector<HTMLElement>(".nline")));
    expect(steps("Tidy styles")).toBeInTheDocument();
  });

  it("shows no section while no chat is working or has steps", async () => {
    const api = withGoals([QUIET], []);
    await openNeedsYou(api);

    await waitFor(() => {
      expect(api.goals).toHaveBeenCalled();
    });
    expect(screen.queryByRole("region", { name: "Goals" })).not.toBeInTheDocument();
  });

  it("shows no goals without a project", async () => {
    const api = withGoals([], [], []);
    await openNeedsYou(api);

    expect(screen.getByText("Nothing needs you.")).toBeInTheDocument();
    expect(api.goals).not.toHaveBeenCalled();
  });

  it("loads no goals after a reconnect that cannot resume, while there is no project", async () => {
    const api = withGoals([], [], []);
    const { sockets } = await openNeedsYou(api);
    const loads = api.approvals.mock.calls.length;

    const count = sockets.sockets.length;
    act(() => {
      sockets.last().drop(1006);
    });
    await waitFor(
      () => {
        expect(sockets.sockets).toHaveLength(count + 1);
      },
      { timeout: 3000 },
    );
    act(() => {
      sockets.last().open();
    });

    // The snapshots load again; there is still no project to load goals for.
    await waitFor(() => {
      expect(api.approvals.mock.calls.length).toBeGreaterThan(loads);
    });
    expect(api.goals).not.toHaveBeenCalled();
  }, 10_000);

  it("opens the chat from its name", async () => {
    const api = withGoals([FINISHED], [{ session_id: "f", tasks: PLAN }]);
    api.session.mockResolvedValue(detail(FINISHED));
    const { user } = await openNeedsYou(api);
    await screen.findByRole("region", { name: "Goals" });

    await user.click(within(goal("Tidy styles")).getByRole("button", { name: "Tidy styles" }));

    expect(await screen.findByRole("region", { name: "Tidy styles" })).toBeInTheDocument();
  });

  it("follows the steps and the chats' states live", async () => {
    const api = withGoals([FINISHED, QUIET], []);
    const { push } = await openNeedsYou(api);
    await waitFor(() => {
      expect(api.goals).toHaveBeenCalled();
    });

    push({
      type: "session.tasks",
      session_id: "f",
      payload: { tasks: PLAN as unknown as JsonValue },
    });
    expect(within(steps("Tidy styles")).getAllByRole("listitem")).toHaveLength(3);

    push({ type: "session.state", session_id: "q", payload: { state: "running" } });
    expect(
      within(goalsRegion())
        .getAllByRole("article")
        .map((a) => a.getAttribute("aria-label")),
    ).toEqual(["Old question: No plan yet, Running", "Tidy styles: 1 of 3, Idle"]);

    // The user's next message cleared the finished list; the other chat went idle.
    push({ type: "session.tasks", session_id: "f", payload: { tasks: [] } });
    expect(within(goalsRegion()).queryByText("Tidy styles")).not.toBeInTheDocument();
    push({ type: "session.state", session_id: "q", payload: { state: "idle" } });
    expect(screen.queryByRole("region", { name: "Goals" })).not.toBeInTheDocument();
  });

  it("follows the project chosen on Chats, and loads again after a reconnect", async () => {
    const other = session({ id: "n", repo: "narrative", title: "Write intro" });
    const api = withGoals([FINISHED, other], [], ["cv-page", "narrative"]);
    const { user, sockets } = await openNeedsYou(api);
    await waitFor(() => {
      expect(api.goals).toHaveBeenCalledWith("cv-page");
    });

    api.goals.mockResolvedValue([{ session_id: "n", tasks: [task({ subject: "Outline" })] }]);
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: "Project: cv-page" }));
    await user.click(screen.getByRole("menuitemradio", { name: /narrative/ }));
    await user.click(screen.getByRole("tab", { name: "Needs you" }));
    expect(
      await within(await screen.findByRole("region", { name: "Goals" })).findByText("Outline"),
    ).toBeInTheDocument();
    expect(api.goals).toHaveBeenLastCalledWith("narrative");

    // Meanwhile the user's next message cleared it, and the event was missed.
    api.goals.mockResolvedValue([]);
    const count = sockets.sockets.length;
    act(() => {
      sockets.last().drop(1006);
    });
    await waitFor(
      () => {
        expect(sockets.sockets).toHaveLength(count + 1);
      },
      { timeout: 3000 },
    );
    act(() => {
      sockets.last().open();
    });

    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Goals" })).not.toBeInTheDocument();
    });
    expect(api.goals).toHaveBeenLastCalledWith("narrative");
  }, 10_000);

  it("keeps what it knows, without a message, when the goals cannot load", async () => {
    const api = withGoals([WORKING], []);
    api.goals.mockRejectedValue(new ApiError(500, "Boom"));
    await openNeedsYou(api);

    await waitFor(() => {
      expect(api.goals).toHaveBeenCalled();
    });
    expect(
      await within(await screen.findByRole("region", { name: "Goals" })).findByText("No plan yet"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Boom")).not.toBeInTheDocument();
  });
});
