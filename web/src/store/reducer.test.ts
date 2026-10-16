import { describe, expect, it } from "vitest";
import type { NestEvent, JsonValue } from "../api/types.ts";
import {
  approval,
  connector,
  event,
  groupEntry,
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
    repos: [repo("cv-page")],
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
      "new:cv-page": draft,
      "new:removed": draft,
      // Pixies arrive after the snapshot, so their drafts stay.
      "pixie:p1": draft,
    };
    const snapshot = {
      type: "loaded" as const,
      repos: [repo("cv-page")],
      sessions: [session()],
      approvals: [],
    };

    const first = reduce({ ...initialState, drafts: saved }, snapshot);
    expect(Object.keys(first.drafts)).toEqual(["session:s1", "new:cv-page", "pixie:p1"]);
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

describe("pixie groups (B46)", () => {
  it("loads every chat's group, then follows each chat's from its events", () => {
    const scribe = groupEntry({ pixie_id: "scribe" });
    let state = reduce(loaded(), { type: "pixieGroups", groups: { s1: [groupEntry()] } });
    expect(state.pixieGroups).toEqual({ s1: [groupEntry()] });

    state = apply(
      state,
      event({ type: "session.pixies", session_id: "s2", payload: { group: [scribe] as never } }),
    );
    expect(state.pixieGroups).toEqual({ s1: [groupEntry()], s2: [scribe] });

    // An empty group leaves; an event without a chat changes nothing.
    state = apply(
      state,
      event({ type: "session.pixies", session_id: "s1", payload: { group: [] } }),
    );
    state = apply(state, event({ type: "session.pixies", session_id: null, payload: {} }));
    expect(state.pixieGroups).toEqual({ s2: [scribe] });

    state = reduce(state, { type: "pixieGroup", id: "s2", group: [] });
    expect(state.pixieGroups).toEqual({});
    state = reduce(state, { type: "pixieGroup", id: "s1", group: [scribe] });
    expect(state.pixieGroups).toEqual({ s1: [scribe] });

    state = apply(state, event({ type: "session.deleted", payload: { session_id: "s1" } }));
    expect(state.pixieGroups).toEqual({});
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
      repos: [repo("cv-page"), plain],
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

    expect(state.repos).toEqual([repo("cv-page"), now]);
    expect(unknown.repos).toEqual(state.repos);
  });

  it("add a registered project and remove an unregistered one", () => {
    const repoEvent = (type: string, payload: Record<string, JsonValue>) =>
      event({ type, session_id: null, payload });
    let state = apply(
      loaded(),
      repoEvent("repo.added", { name: "notes", repo: repo("notes") as unknown as JsonValue }),
    );
    expect(state.repos.map((r) => r.name)).toEqual(["cv-page", "notes"]);
    // Added again, as a replay after a snapshot that already had it: still one, in place.
    const again = apply(
      state,
      repoEvent("repo.added", { name: "cv-page", repo: repo("cv-page") as unknown as JsonValue }),
    );
    expect(again.repos.map((r) => r.name)).toEqual(["cv-page", "notes"]);

    state = apply(state, repoEvent("repo.removed", { name: "cv-page" }));
    expect(state.repos.map((r) => r.name)).toEqual(["notes"]);
  });

  it("sort the projects by a new shared order, keeping unlisted ones after", () => {
    const state = reduce(loaded(), {
      type: "loaded",
      repos: [repo("alpha"), repo("beta"), repo("gamma"), repo("delta")],
      sessions: [],
      approvals: [],
    });

    const reordered = apply(
      state,
      event({
        type: "repos.reordered",
        session_id: null,
        payload: { order: ["gamma", "gone", "alpha"] },
      }),
    );

    expect(reordered.repos.map((r) => r.name)).toEqual(["gamma", "alpha", "beta", "delta"]);
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

  it("drop the events a conversation rewind removed (B59)", () => {
    const said = (id: number, sessionId = "s1") =>
      event({ id, session_id: sessionId, type: "session.user_message", payload: { text: "x" } });
    let state = reduce(loaded(), { type: "transcriptOpened", id: "s1" });
    state = reduce(state, { type: "transcriptOpened", id: "s2" });
    state = reduce(state, { type: "transcriptLoaded", id: "s1", events: [said(3), said(5)] });
    state = reduce(state, { type: "transcriptLoaded", id: "s2", events: [said(6, "s2")] });
    state = apply(state, said(7));
    state = apply(state, said(8));
    const rewound = event({
      id: 9,
      type: "session.rewound",
      payload: { message: 5, through: 7, text: "x", attachments: [] },
    });

    state = apply(state, rewound);

    expect(state.transcripts.s1?.map((e) => e.id)).toEqual([3, 8, 9]);
    expect(state.transcripts.s2?.map((e) => e.id)).toEqual([6]);
    // A malformed one, or one for a chat not open, changes nothing.
    const bare = event({ id: 10, type: "session.rewound", payload: {} });
    expect(apply(state, bare).transcripts.s1?.map((e) => e.id)).toEqual([3, 8, 9, 10]);
    const closed = event({ id: 11, session_id: "s9", type: "session.rewound", payload: {} });
    expect(apply(state, closed).transcripts).toBe(state.transcripts);
    const global = event({ id: 12, session_id: null, type: "session.rewound", payload: {} });
    expect(apply(state, global).transcripts).toBe(state.transcripts);
  });

  it("keep the chat's shell commands until a message carries them (B59)", () => {
    const result = {
      command: "ls",
      exit_code: 0,
      output: "a",
      truncated: false,
      timed_out: false,
      context: "<bash-input>ls</bash-input>",
    };
    let state = reduce(loaded(), { type: "bashStarted", id: "s1", runId: 1, command: "ls" });
    state = reduce(state, { type: "bashStarted", id: "s1", runId: 2, command: "pwd" });
    state = reduce(state, { type: "bashStarted", id: "s2", runId: 3, command: "id" });
    state = reduce(state, { type: "bashFinished", id: "s1", runId: 1, result });
    state = reduce(state, { type: "bashFinished", id: "s1", runId: 2, error: "folder gone" });
    // One for a chat or run no longer there changes nothing.
    expect(reduce(state, { type: "bashFinished", id: "s9", runId: 1, error: "x" })).toEqual(state);

    expect(state.bash.s1).toEqual([
      { id: 1, command: "ls", result, error: null },
      { id: 2, command: "pwd", result: null, error: "folder gone" },
    ]);
    state = reduce(state, { type: "bashSent", id: "s1", runIds: [1, 2] });
    expect(state.bash.s1).toEqual([]);
    expect(state.bash.s2).toHaveLength(1);
    state = apply(state, event({ type: "session.deleted", payload: { session_id: "s2" } }));
    expect(state.bash.s2).toBeUndefined();
  });

  it("fill a draft with a message taken back", () => {
    const file = { id: "a1", filename: "a.png", media_type: "image/png", size: 3, created_at: "" };
    let state = reduce(loaded(), { type: "draftText", key: "session:s1", text: "old" });
    state = reduce(state, { type: "draftFilled", key: "session:s1", text: "Again", files: [file] });

    expect(state.drafts["session:s1"]).toEqual({ text: "Again", files: [file] });
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
  describe("streams (B59)", () => {
    const delta = (type: string, text: string, parent: string | null = null) =>
      event({ id: null, type, payload: { text, parent_tool_use_id: parent } });

    it("streams the main agent's thinking text until its block arrives", () => {
      let state = apply(
        loaded(),
        event({ id: null, type: "session.thinking", payload: { active: true } }),
      );
      state = apply(state, delta("session.thinking_delta", "Let me check "));
      state = apply(state, delta("session.thinking_delta", "the test"));
      expect(state.thoughts).toEqual({ s1: "Let me check the test" });
      // A subagent's thinking is not the main agent's.
      expect(apply(state, delta("session.thinking_delta", "sub", "a1")).thoughts).toEqual(
        state.thoughts,
      );
      expect(apply(state, event({ type: "session.message" })).thoughts).toEqual({});
      expect(
        apply(state, event({ id: null, type: "session.thinking", payload: { active: true } }))
          .thoughts,
      ).toEqual({});
      expect(
        apply(state, event({ type: "session.state", payload: { state: "idle" } })).thoughts,
      ).toEqual({});
      expect(apply(state, { ...delta("session.thinking_delta", "x"), session_id: null })).toBe(
        state,
      );
    });

    it("streams a subagent's text under its call, apart from the main text", () => {
      let state = apply(loaded(), delta("session.subagent_delta", "Found 3 ", "a1"));
      state = apply(state, delta("session.subagent_delta", "call sites", "a1"));
      state = apply(state, delta("session.subagent_delta", "Other", "a2"));
      state = apply(state, delta("session.delta", "Main"));
      expect(state.agentLive).toEqual({ s1: { a1: "Found 3 call sites", a2: "Other" } });
      expect(state.live).toEqual({ s1: "Main" });
      expect(apply(state, delta("session.subagent_delta", "x"))).toBe(state);
      expect(
        apply(state, { ...delta("session.subagent_delta", "x", "a1"), session_id: null }),
      ).toBe(state);

      // A subagent's message replaces its streamed text, and leaves the main text alone.
      const sub = apply(
        state,
        event({ type: "session.message", payload: { parent_tool_use_id: "a1", blocks: [] } }),
      );
      expect(sub.agentLive).toEqual({ s1: { a2: "Other" } });
      expect(sub.live).toEqual({ s1: "Main" });
      const other = event({
        type: "session.message",
        payload: { parent_tool_use_id: "zz", blocks: [] },
      });
      expect(apply(state, other)).toBe(state);
      expect(apply(state, { ...other, session_id: null })).toBe(state);
      expect(
        apply(
          state,
          event({
            id: null,
            type: "session.subagent_delta",
            payload: { parent_tool_use_id: "a2" },
          }),
        ).agentLive,
      ).toEqual(state.agentLive);
      const main = apply(state, event({ type: "session.message", payload: { blocks: [] } }));
      expect(main.agentLive).toEqual(state.agentLive);
      expect(main.live).toEqual({});

      // Leaving running drops them all; running itself keeps them.
      expect(
        apply(state, event({ type: "session.state", payload: { state: "running" } })).agentLive,
      ).toEqual(state.agentLive);
      expect(
        apply(state, event({ type: "session.state", payload: { state: "idle" } })).agentLive,
      ).toEqual({});
      expect(reduce(state, { type: "liveCleared", id: "s1" }).agentLive).toEqual({});
      expect(reduce(state, { type: "sessionRemoved", id: "s1" }).agentLive).toEqual({});
      // Replayed stored events keep what streamed meanwhile.
      expect(
        reduce(state, { type: "replayed", events: [event({ type: "session.message" })] }).agentLive,
      ).toEqual(state.agentLive);
    });
  });
});
