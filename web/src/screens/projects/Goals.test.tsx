import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { Goal, JsonValue, Session, TrackedTask } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { detail, repo, session, task } from "../../test/fixtures.ts";
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
  // The chat list's own load of a working chat's detail agrees with the goals.
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

async function openProjects(api: FakeApi) {
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  return rendered;
}

const goalsRegion = () => screen.getByRole("region", { name: "Goals" });
const steps = (title: string) =>
  within(goalsRegion()).getByRole("list", { name: `Steps of ${title}` });

describe("the project's goals (B47)", () => {
  it("shows each chat's steps under its title, working chats first", async () => {
    const api = withGoals(
      [FINISHED, WORKING, QUIET],
      [
        { session_id: "w", tasks: [] },
        { session_id: "f", tasks: PLAN },
      ],
    );
    await openProjects(api);

    await screen.findByRole("region", { name: "Goals" });
    expect(api.goals).toHaveBeenCalledWith("cv-page");
    const headings = within(goalsRegion()).getAllByRole("heading", { level: 3 });
    expect(headings.map((h) => h.textContent)).toEqual([
      expect.stringContaining("Fix the header"),
      expect.stringContaining("Tidy styles"),
    ]);
    // The section sits above the chat groups.
    const firstGroup = screen.getByRole("heading", { level: 2, name: /Running/ });
    expect(
      goalsRegion().compareDocumentPosition(firstGroup) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    expect(
      within(goalsRegion()).getByRole("button", { name: "Fix the header: no plan yet, Running" }),
    ).toBeInTheDocument();
    expect(within(goalsRegion()).getByText("No plan yet")).toBeInTheDocument();
    expect(
      within(goalsRegion()).getByRole("button", { name: "Tidy styles: 1 of 3 done, Idle" }),
    ).toBeInTheDocument();
    const items = within(steps("Tidy styles")).getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual([
      "done: Read the form",
      "in progress: Adding checks",
      "pending: Write tests",
    ]);
    expect(screen.queryByText("Old question", { selector: ".gs-t" })).not.toBeInTheDocument();
  });

  it("shows no section while no chat is working or has steps", async () => {
    const api = withGoals([QUIET], []);
    await openProjects(api);

    await waitFor(() => {
      expect(api.goals).toHaveBeenCalled();
    });
    expect(screen.getByRole("button", { name: /^Old question,/ })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Goals" })).not.toBeInTheDocument();
  });

  it("opens the chat from its heading", async () => {
    const api = withGoals([FINISHED], [{ session_id: "f", tasks: PLAN }]);
    api.session.mockResolvedValue(detail(FINISHED));
    const { user } = await openProjects(api);

    await user.click(await screen.findByRole("button", { name: "Tidy styles: 1 of 3 done, Idle" }));

    expect(await screen.findByRole("region", { name: "Tidy styles" })).toBeInTheDocument();
  });

  it("follows the steps and the chats' states live", async () => {
    const api = withGoals([FINISHED, QUIET], []);
    const { push } = await openProjects(api);
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
    const headings = within(goalsRegion()).getAllByRole("heading", { level: 3 });
    expect(headings.map((h) => h.textContent)).toEqual([
      expect.stringContaining("Old question"),
      expect.stringContaining("Tidy styles"),
    ]);

    // The user's next message cleared the finished list; the other chat went idle.
    push({ type: "session.tasks", session_id: "f", payload: { tasks: [] } });
    expect(within(goalsRegion()).queryByText("Tidy styles")).not.toBeInTheDocument();
    push({ type: "session.state", session_id: "q", payload: { state: "idle" } });
    expect(screen.queryByRole("region", { name: "Goals" })).not.toBeInTheDocument();
  });

  it("loads again for another project and after a reconnect that cannot resume", async () => {
    const other = session({ id: "n", repo: "narrative", title: "Write intro" });
    const api = withGoals([FINISHED, other], [], ["cv-page", "narrative"]);
    const { user, sockets } = await openProjects(api);
    await waitFor(() => {
      expect(api.goals).toHaveBeenCalledWith("cv-page");
    });

    api.goals.mockResolvedValue([{ session_id: "n", tasks: [task({ subject: "Outline" })] }]);
    await user.click(screen.getByRole("tab", { name: /narrative/ }));
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
    await openProjects(api);

    await waitFor(() => {
      expect(api.goals).toHaveBeenCalled();
    });
    expect(
      await within(await screen.findByRole("region", { name: "Goals" })).findByText("No plan yet"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Boom")).not.toBeInTheDocument();
  });
});
