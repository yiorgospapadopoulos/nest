import { describe, expect, it } from "vitest";
import type { NestEvent, JsonValue } from "../api/types.ts";
import {
  approval,
  connector,
  event,
  habit,
  habitRun,
  NO_BACKGROUND,
  NOW,
  pixie,
  prStatus,
  question,
  queuedMessage,
  report,
  repo,
  review,
  session,
  team,
} from "../test/fixtures.ts";
import { reduce } from "./reducer.ts";
import { initialState, type State } from "./state.ts";

function loaded(): State {
  return reduce(initialState, {
    type: "loaded",
    repos: [repo("todo-ui")],
    sessions: [session(), session({ id: "s2", title: "Other" })],
    approvals: [approval(), review({ status: "resolved" })],
  });
}

const apply = (state: State, e: NestEvent) => reduce(state, { type: "event", event: e });

describe("reduce", () => {
  it("loads snapshots, keeping only pending approvals", () => {
    const state = loaded();

    expect(state.auth).toBe("ready");
    expect(Object.keys(state.sessions)).toEqual(["s1", "s2"]);
    expect(Object.keys(state.approvals)).toEqual(["q1"]);
    expect(reduce(state, { type: "auth", auth: "unpaired" }).auth).toBe("unpaired");
  });

  it("keeps pixie chats, which the session list leaves out, across a reload", () => {
    const withChat = reduce(loaded(), {
      type: "session",
      session: session({ id: "c1", repo: "pixie:p1", pixie_id: "p1" }),
    });
    const reloaded = reduce(withChat, {
      type: "loaded",
      repos: [],
      sessions: [session({ id: "s2" })],
      approvals: [],
    });

    expect(Object.keys(reloaded.sessions).sort()).toEqual(["c1", "s2"]);
  });

  it("drops saved drafts of chats and projects gone while the app was closed", () => {
    const draft = { text: "x", files: [] };
    const saved = {
      "session:s1": draft,
      "session:gone": draft,
      "new:todo-ui": draft,
      "new:removed": draft,
      // Pixies arrive after the snapshot, so their drafts stay.
      "pixie:p1": draft,
    };
    const snapshot = {
      type: "loaded" as const,
      repos: [repo("todo-ui")],
      sessions: [session()],
      approvals: [],
    };

    const first = reduce({ ...initialState, drafts: saved }, snapshot);
    expect(Object.keys(first.drafts)).toEqual(["session:s1", "new:todo-ui", "pixie:p1"]);
    // Later snapshots, after a reconnect, leave drafts to the live events.
    const later = reduce({ ...first, drafts: saved }, snapshot);
    expect(later.drafts).toBe(saved);
  });

  it("tracks a reconnect until the socket opens or the device has to pair again", () => {
    const lost = reduce(loaded(), { type: "reconnecting", on: true });
    expect(lost.reconnecting).toBe(true);
    expect(reduce(lost, { type: "reconnecting", on: false }).reconnecting).toBe(false);
    expect(reduce(lost, { type: "auth", auth: "unpaired" }).reconnecting).toBe(false);
  });

  it("upserts and removes sessions with everything that belongs to them", () => {
    let state = reduce(loaded(), { type: "session", session: session({ title: "Renamed" }) });
    state = reduce(state, {
      type: "tracking",
      id: "s1",
      tracking: { tasks: [], agents: [], background: NO_BACKGROUND },
    });
    state = reduce(state, { type: "transcriptOpened", id: "s1" });
    state = reduce(state, { type: "queued", id: "s1", queued: [queuedMessage()] });
    state = apply(state, event({ id: null, type: "session.delta", payload: { text: "Hi" } }));
    state = apply(state, event({ id: null, type: "session.thinking", payload: { active: true } }));
    expect(state.sessions.s1?.title).toBe("Renamed");

    state = reduce(state, { type: "sessionRemoved", id: "s1" });

    expect(state.sessions.s1).toBeUndefined();
    expect(state.approvals).toEqual({});
    expect(state.tracking).toEqual({});
    expect(state.transcripts).toEqual({});
    expect(state.live).toEqual({});
    expect(state.thinking).toEqual({});
    expect(state.queued).toEqual({});
    expect(state.sessions.s2).toBeDefined();
  });

  it("keeps queued messages per session and drops a cancelled one", () => {
    const first = queuedMessage();
    const second = queuedMessage({ id: "m2" });
    let state = reduce(loaded(), { type: "queued", id: "s1", queued: [first, second] });

    state = reduce(state, { type: "queuedRemoved", id: "s1", queuedId: "m1" });
    expect(state.queued.s1).toEqual([second]);
    state = reduce(state, { type: "queuedRemoved", id: "s2", queuedId: "m2" });
    expect(state.queued.s2).toEqual([]);
  });

  it("keeps approvals while pending", () => {
    let state = reduce(loaded(), { type: "approval", approval: question() });
    expect(Object.keys(state.approvals)).toEqual(["q1", "q2"]);

    state = reduce(state, { type: "approval", approval: question({ status: "expired" }) });
    expect(Object.keys(state.approvals)).toEqual(["q1"]);
  });

  it("merges a loaded transcript with live events that came first", () => {
    let state = reduce(loaded(), { type: "transcriptOpened", id: "s1" });
    state = apply(state, event({ id: 5, type: "session.message" }));
    state = apply(state, event({ id: 5, type: "duplicate" }));
    state = apply(state, event({ id: 6, type: "other session", session_id: "s2" }));

    state = reduce(state, {
      type: "transcriptLoaded",
      id: "s1",
      events: [event({ id: 3, type: "a" }), event({ id: 5, type: "session.message" })],
    });

    expect(state.transcripts.s1?.map((e) => e.id)).toEqual([3, 5]);
    expect(state.transcripts.s2).toBeUndefined();
    expect(reduce(state, { type: "transcriptOpened", id: "s1" }).transcripts.s1).toHaveLength(2);
    const fresh = reduce(loaded(), { type: "transcriptLoaded", id: "s9", events: [] });
    expect(fresh.transcripts.s9).toEqual([]);
  });

  it("marks a failed history load only while the open chat is still loading", () => {
    let state = reduce(loaded(), { type: "transcriptOpened", id: "s1" });
    expect(state.history.s1).toBe("loading");
    state = reduce(state, { type: "historyFailed", id: "s1" });
    expect(state.history.s1).toBe("failed");

    state = reduce(state, { type: "transcriptLoaded", id: "s1", events: [] });
    // A later refresh that fails keeps what is shown, and a closed chat has no status.
    expect(reduce(state, { type: "historyFailed", id: "s1" })).toBe(state);
    expect(reduce(state, { type: "historyFailed", id: "s2" })).toBe(state);
    expect(reduce(state, { type: "transcriptClosed", id: "s1" }).history).toEqual({});
  });

  it("takes only what was sent out of a draft", () => {
    const file = (id: string) => ({
      id,
      filename: id,
      media_type: "text/plain",
      size: 1,
      created_at: NOW,
    });
    let state = reduce(initialState, { type: "draftText", key: "k", text: "Sent part and more" });
    state = reduce(state, { type: "draftFileAdded", key: "k", file: file("a") });
    state = reduce(state, { type: "draftFileAdded", key: "k", file: file("b") });

    state = reduce(state, { type: "draftSent", key: "k", text: "Sent part", fileIds: ["a"] });
    expect(state.drafts.k).toEqual({ text: "and more", files: [file("b")] });
    // A sent part edited while it went out: all the text stays.
    const edited = reduce(state, { type: "draftSent", key: "k", text: "Other", fileIds: [] });
    expect(edited.drafts.k?.text).toBe("and more");
    const all = reduce(state, { type: "draftSent", key: "k", text: "and more", fileIds: ["b"] });
    expect(all.drafts).toEqual({});
    // The chat went away while its message was sent: nothing to take out.
    expect(reduce(all, { type: "draftSent", key: "k", text: "x", fileIds: [] }).drafts).toEqual({});
  });

  it("stores connectors, limits and toasts", () => {
    let state = reduce(initialState, { type: "connectors", connectors: [connector()] });
    state = reduce(state, {
      type: "limits",
      limits: { five_hour: null, seven_day: null },
    });
    state = reduce(state, { type: "toast", toast: { id: 1, text: "Hi", tone: "ok" } });

    expect(state.connectors).toHaveLength(1);
    expect(state.limits).toEqual({ five_hour: null, seven_day: null });
    expect(state.toast?.text).toBe("Hi");
  });
});

describe("live events", () => {
  it("track created, updated and deleted sessions", () => {
    let state = apply(
      loaded(),
      event({
        type: "session.created",
        payload: { session: { ...session({ id: "s3" }) } as never },
      }),
    );
    state = apply(
      state,
      event({
        type: "session.updated",
        payload: { session: { ...session({ pinned: true }) } as never },
      }),
    );
    expect(state.sessions.s3).toBeDefined();
    expect(state.sessions.s1?.pinned).toBe(true);

    state = apply(state, event({ type: "session.deleted", session_id: null, payload: {} }));
    expect(Object.keys(state.sessions)).toHaveLength(3);
    state = apply(state, event({ type: "session.deleted", payload: { session_id: "s3" } }));
    expect(state.sessions.s3).toBeUndefined();
  });

  it("patch the state, workspace and pull request of known sessions", () => {
    let state = apply(
      loaded(),
      event({ type: "session.state", payload: { state: "failed", error: "boom" } }),
    );
    state = apply(
      state,
      event({ type: "session.workspace", payload: { path: "/w/x", branch: "agent/x" } }),
    );
    state = apply(state, event({ type: "pr.opened", payload: { url: "https://pr/1" } }));

    expect(state.sessions.s1).toMatchObject({
      state: "failed",
      last_error: "boom",
      branch: "agent/x",
      worktree_path: "/w/x",
      pr_url: "https://pr/1",
    });
    const pr = prStatus();
    state = apply(
      state,
      event({ type: "session.pr", payload: { pr: pr as unknown as JsonValue } }),
    );
    expect(state.sessions.s1?.pr).toEqual(pr);
    state = apply(state, event({ type: "session.pr", payload: { pr: "garbled" } }));
    expect(state.sessions.s1?.pr).toBeNull();
    expect(state.sessions.s1?.git_violation).toBe(false);
    state = apply(
      state,
      event({ type: "session.git_violation", payload: { changes: ["refs/heads/x"] } }),
    );
    expect(state.sessions.s1?.git_violation).toBe(true);
    const unknown = apply(state, event({ type: "session.state", session_id: "nope" }));
    expect(unknown).toBe(state);
    expect(apply(state, event({ type: "session.state", session_id: null }))).toBe(state);
  });

  it("track approvals as they are created and resolved", () => {
    let state = apply(
      loaded(),
      event({ type: "approval.created", payload: { approval: { ...question() } } }),
    );
    expect(state.approvals.q2).toBeDefined();
    state = apply(
      state,
      event({
        type: "approval.resolved",
        payload: { approval: { ...question({ status: "resolved" }) } },
      }),
    );
    expect(state.approvals.q2).toBeUndefined();
  });

  it("track the task list and agents", () => {
    const task = { id: "1", subject: "Read", description: null, active_form: null };
    let state = apply(
      loaded(),
      event({ type: "session.tasks", payload: { tasks: [{ ...task, status: "pending" }] } }),
    );
    state = apply(
      state,
      event({ type: "session.agents", payload: { agents: [{ id: "main", name: "main" }] } }),
    );
    expect(state.tracking.s1?.tasks).toHaveLength(1);
    expect(state.tracking.s1?.agents).toHaveLength(1);
    expect(state.tracking.s1?.background).toEqual(NO_BACKGROUND);
    const background = { running: 1, completed: 0, items: [] };
    state = apply(state, event({ type: "session.agents", payload: { agents: [], background } }));
    expect(state.tracking.s1?.background).toEqual(background);
    expect(state.tracking.s1?.agents).toEqual([]);
    expect(apply(state, event({ type: "session.tasks", session_id: null }))).toBe(state);
  });

  it("marks when the agent started thinking until the thinking or the turn ends", () => {
    const thinking = (active: boolean, ts = "2026-01-01T12:00:05Z") =>
      event({ id: null, type: "session.thinking", ts, payload: { active } });
    let state = apply(loaded(), thinking(true));
    expect(state.thinking).toEqual({ s1: "2026-01-01T12:00:05Z" });
    expect(apply(state, thinking(false)).thinking).toEqual({});
    expect(apply(state, event({ type: "session.message" })).thinking).toEqual({});
    expect(apply(state, event({ type: "session.result" })).thinking).toEqual({});
    expect(
      apply(state, event({ type: "session.state", payload: { state: "idle" } })).thinking,
    ).toEqual({});
    expect(apply(state, { ...thinking(true), session_id: null })).toBe(state);

    state = apply(state, thinking(false));
    expect(apply(state, thinking(false))).toBe(state);
  });

  it("stream text deltas until the message or result arrives", () => {
    let state = apply(
      loaded(),
      event({ id: null, type: "session.delta", payload: { text: "He" } }),
    );
    state = apply(state, event({ id: null, type: "session.delta", payload: { text: "llo" } }));
    state = apply(state, event({ id: null, type: "session.delta", payload: {} }));
    expect(state.live.s1).toBe("Hello");
    expect(apply(state, event({ id: null, type: "session.delta", session_id: null }))).toBe(state);

    state = apply(state, event({ type: "session.message" }));
    expect(state.live.s1).toBeUndefined();
    expect(apply(state, event({ type: "session.result" }))).toEqual(state);
    expect(apply(state, event({ type: "session.result", session_id: null }))).toEqual(state);
  });

  it("track connectors and usage windows", () => {
    let state = apply(
      loaded(),
      event({
        type: "connectors.updated",
        session_id: null,
        payload: { connectors: [{ ...connector() }] },
      }),
    );
    state = apply(
      state,
      event({
        type: "usage.updated",
        session_id: null,
        payload: { five_hour: { utilization: 0.5, resets_at: NOW }, seven_day: null },
      }),
    );

    expect(state.connectors).toHaveLength(1);
    expect(state.limits).toEqual({
      five_hour: { utilization: 0.5, resets_at: NOW, updated_at: NOW },
      seven_day: null,
    });
  });

  it("replace a repo that changed, such as a plain folder that became a git repo", () => {
    const plain = { ...repo("notes"), git: false, default_branch: null };
    let state = reduce(loaded(), {
      type: "loaded",
      repos: [repo("todo-ui"), plain],
      sessions: [],
      approvals: [],
    });
    const now = { ...repo("notes"), git: true, default_branch: "main" };

    state = apply(
      state,
      event({
        type: "repo.updated",
        session_id: null,
        payload: { name: "notes", repo: now as unknown as JsonValue },
      }),
    );
    const unknown = apply(
      state,
      event({
        type: "repo.updated",
        session_id: null,
        payload: { name: "gone", repo: repo("gone") as unknown as JsonValue },
      }),
    );

    expect(state.repos).toEqual([repo("todo-ui"), now]);
    expect(unknown.repos).toEqual(state.repos);
  });

  it("add a registered project and remove an unregistered one", () => {
    const repoEvent = (type: string, payload: Record<string, JsonValue>) =>
      event({ type, session_id: null, payload });
    let state = apply(
      loaded(),
      repoEvent("repo.added", { name: "notes", repo: repo("notes") as unknown as JsonValue }),
    );
    expect(state.repos.map((r) => r.name)).toEqual(["todo-ui", "notes"]);
    // Added again, as a replay after a snapshot that already had it: still one, in place.
    const again = apply(
      state,
      repoEvent("repo.added", { name: "todo-ui", repo: repo("todo-ui") as unknown as JsonValue }),
    );
    expect(again.repos.map((r) => r.name)).toEqual(["todo-ui", "notes"]);

    state = apply(state, repoEvent("repo.removed", { name: "todo-ui" }));
    expect(state.repos.map((r) => r.name)).toEqual(["notes"]);
  });

  it("keep a usage window the event leaves out, as the daemon does", () => {
    const earlier = { utilization: 0.2, resets_at: null, updated_at: "2026-10-06T08:00:00Z" };
    const state = apply(
      { ...loaded(), limits: { five_hour: null, seven_day: earlier } },
      event({
        type: "usage.updated",
        session_id: null,
        payload: { five_hour: { utilization: 0.5, resets_at: NOW } },
      }),
    );

    expect(state.limits).toEqual({
      five_hour: { utilization: 0.5, resets_at: NOW, updated_at: NOW },
      seven_day: earlier,
    });
  });

  it("replace the queue with the latest list", () => {
    const queued = [{ ...queuedMessage() }] as never;
    let state = apply(loaded(), event({ type: "session.queued", payload: { queued } }));
    expect(state.queued.s1).toEqual([queuedMessage()]);

    state = apply(state, event({ type: "session.queued", payload: { queued: [] } }));
    expect(state.queued.s1).toEqual([]);
    expect(apply(state, event({ type: "session.queued", session_id: null }))).toBe(state);
  });

  it("track the context window of known sessions", () => {
    const context = { percent: 41.4, used: 82_000, limit: 200_000 };
    let state = apply(loaded(), event({ type: "session.context", payload: { context } }));
    expect(state.sessions.s1?.context).toEqual(context);

    state = apply(state, event({ type: "session.context", payload: { context: null } }));
    expect(state.sessions.s1?.context).toBeNull();
  });

  it("track whether a session looks stuck", () => {
    const flag = { reason: "silent", since: NOW, details: "No new output for 10 minutes" };
    let state = apply(loaded(), event({ type: "session.stuck", payload: flag }));
    expect(state.sessions.s1?.stuck).toEqual(flag);

    state = apply(state, event({ type: "session.unstuck", payload: { reason: "silent" } }));
    expect(state.sessions.s1?.stuck).toBeNull();
  });

  it("ignore unknown event types", () => {
    const state = loaded();
    expect(apply(state, event({ type: "daemon.started", session_id: null }))).toBe(state);
  });

  it("keeps pixies from events", () => {
    let state = reduce(initialState, { type: "pixies", pixies: [pixie({ id: "a" })] });
    state = apply(
      state,
      event({
        type: "pixie.updated",
        payload: { pixie: pixie({ id: "b", position: 1 }) } as never,
      }),
    );
    expect(Object.keys(state.pixies)).toEqual(["a", "b"]);
    state = reduce(state, { type: "pixie", pixie: pixie({ id: "c" }) });
    state = apply(state, event({ type: "pixie.deleted", payload: { pixie_id: "a" } }));
    state = apply(state, event({ type: "pixie.deleted", payload: {} }));
    state = reduce(state, { type: "pixieRemoved", id: "c" });
    expect(Object.keys(state.pixies)).toEqual(["b"]);
  });

  it("drops a removed pixie's saved draft, however it goes", () => {
    const draft = { text: "hi", files: [] };
    let state = reduce(initialState, {
      type: "pixies",
      pixies: [pixie({ id: "a" }), pixie({ id: "b", position: 1 })],
    });
    state = { ...state, drafts: { "pixie:a": draft, "pixie:b": draft, "session:s1": draft } };
    state = reduce(state, { type: "pixieRemoved", id: "a" });
    expect(Object.keys(state.drafts)).toEqual(["pixie:b", "session:s1"]);
    state = apply(state, event({ type: "pixie.deleted", payload: { pixie_id: "b" } }));
    expect(Object.keys(state.drafts)).toEqual(["session:s1"]);
  });

  it("keeps teams from loads and events, and frees the pixies of a deleted team", () => {
    let state = reduce(initialState, {
      type: "pixies",
      pixies: [pixie({ id: "a", team_id: "t1" }), pixie({ id: "b", team_id: "t2" })],
    });
    state = reduce(state, { type: "teams", teams: [team({ id: "t1" }), team({ id: "t2" })] });
    state = apply(
      state,
      event({
        type: "pixie_team.updated",
        payload: { team: team({ id: "t1", leader_id: "a" }) } as never,
      }),
    );
    expect(state.teams.t1?.leader_id).toBe("a");
    state = reduce(state, { type: "team", team: team({ id: "t3", name: "Docs" }) });
    expect(Object.keys(state.teams)).toEqual(["t1", "t2", "t3"]);

    state = apply(state, event({ type: "pixie_team.deleted", payload: { id: "t1" } }));
    state = apply(state, event({ type: "pixie_team.deleted", payload: {} }));
    expect(Object.keys(state.teams)).toEqual(["t2", "t3"]);
    expect(state.pixies.a?.team_id).toBeNull();
    state = reduce(state, { type: "teamRemoved", id: "t2" });
    expect(Object.keys(state.teams)).toEqual(["t3"]);
    expect(state.pixies.b?.team_id).toBeNull();
  });

  it("remembers which teams are folded", () => {
    let state = reduce(initialState, { type: "teamFolded", id: "t1", folded: true });
    state = reduce(state, { type: "teamFolded", id: "t2", folded: true });
    state = reduce(state, { type: "teamFolded", id: "t1", folded: true });
    expect(state.foldedTeams).toEqual(["t1", "t2"]);
    state = reduce(state, { type: "teamFolded", id: "t1", folded: false });
    expect(state.foldedTeams).toEqual(["t2"]);
  });

  it("drops the drafts of pixies deleted while the app was closed once pixies load", () => {
    const draft = { text: "hi", files: [] };
    const state = reduce(
      { ...initialState, drafts: { "pixie:a": draft, "pixie:gone": draft, "session:s1": draft } },
      { type: "pixies", pixies: [pixie({ id: "a" })] },
    );
    expect(Object.keys(state.drafts)).toEqual(["pixie:a", "session:s1"]);
  });

  it("keeps reports, adds new ones and marks them read (B42)", () => {
    let state = reduce(initialState, {
      type: "reports",
      reports: [report({ id: "a" }), report({ id: "b" })],
    });
    state = apply(
      state,
      event({ type: "pixie.report", payload: { report: report({ id: "c" }) } as never }),
    );
    expect(Object.keys(state.reports)).toEqual(["a", "b", "c"]);

    state = apply(
      state,
      event({ type: "pixie.report_read", ts: NOW, payload: { ids: ["a", "gone"] } }),
    );
    expect(state.reports.a?.read_at).toBe(NOW);
    expect(state.reports.b?.read_at).toBeNull();
    // A report read already keeps when it was read.
    state = reduce(state, { type: "reportsRead", ids: ["a", "b"], at: "2026-10-15T00:00:00Z" });
    expect(state.reports.a?.read_at).toBe(NOW);
    expect(state.reports.b?.read_at).toBe("2026-10-15T00:00:00Z");
    expect(apply(state, event({ type: "pixie.report_read", payload: {} })).reports).toBe(
      state.reports,
    );
  });

  it("keeps the habits of pixies whose list was loaded, live (B42)", () => {
    let state = reduce(initialState, {
      type: "habits",
      pixieId: "p1",
      habits: [habit({ id: "h1" })],
    });
    state = apply(
      state,
      event({ type: "habit.updated", payload: { habit: habit({ id: "h2" }) } as never }),
    );
    state = apply(
      state,
      event({
        type: "habit.updated",
        payload: { habit: habit({ id: "h1", name: "Renamed" }) } as never,
      }),
    );
    // A pixie whose list is not loaded gets no partial list.
    state = apply(
      state,
      event({
        type: "habit.updated",
        payload: { habit: habit({ id: "h9", pixie_id: "p2" }) } as never,
      }),
    );
    expect(state.habits.p1?.map((h) => [h.id, h.name])).toEqual([
      ["h1", "Renamed"],
      ["h2", "Morning check"],
    ]);
    expect(state.habits.p2).toBeUndefined();

    state = apply(state, event({ type: "habit.deleted", payload: { id: "h1", pixie_id: "p1" } }));
    state = apply(state, event({ type: "habit.deleted", payload: { id: "h9", pixie_id: "p2" } }));
    state = apply(state, event({ type: "habit.deleted", payload: {} }));
    expect(state.habits.p1?.map((h) => h.id)).toEqual(["h2"]);
    expect(state.habits.p2).toBeUndefined();
  });

  it("follows habit runs in the history and the habit's last run (B42)", () => {
    let state = reduce(initialState, {
      type: "habits",
      pixieId: "p1",
      habits: [habit({ id: "h1" }), habit({ id: "h2" })],
    });
    state = reduce(state, {
      type: "habitRuns",
      habitId: "h1",
      runs: [habitRun({ id: "r1" })],
    });
    const queued = habitRun({ id: "r2", outcome: "queued", started_at: null });
    state = apply(state, event({ type: "habit.run_updated", payload: { run: queued } as never }));
    state = apply(
      state,
      event({
        type: "habit.run_updated",
        payload: { run: { ...queued, outcome: "running" } },
      }),
    );
    expect(state.habitRuns.h1?.map((r) => [r.id, r.outcome])).toEqual([
      ["r2", "running"],
      ["r1", "reported"],
    ]);
    expect(state.habits.p1?.[0]?.last_run?.outcome).toBe("running");
    expect(state.habits.p1?.[1]?.last_run).toBeNull();

    // A run of a habit whose history is not open, of a pixie whose list is not loaded.
    const other = habitRun({ id: "r3", habit_id: "h7", pixie_id: "p2" });
    state = apply(state, event({ type: "habit.run_updated", payload: { run: other } as never }));
    expect(state.habitRuns.h7).toBeUndefined();
    expect(state.habits.p2).toBeUndefined();
  });

  it("forgets a deleted pixie's habits and reports (B42)", () => {
    let state = reduce(initialState, { type: "pixies", pixies: [pixie({ id: "p1" })] });
    state = reduce(state, { type: "habits", pixieId: "p1", habits: [habit()] });
    state = reduce(state, {
      type: "reports",
      reports: [report({ id: "a" }), report({ id: "b", pixie_id: "p2" })],
    });
    state = apply(state, event({ type: "pixie.deleted", payload: { pixie_id: "p1" } }));
    expect(state.habits.p1).toBeUndefined();
    expect(Object.keys(state.reports)).toEqual(["b"]);
  });
});
