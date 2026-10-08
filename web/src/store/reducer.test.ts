import { describe, expect, it } from "vitest";
import type { HarnessEvent, JsonValue } from "../api/types.ts";
import {
  approval,
  connector,
  event,
  NO_BACKGROUND,
  NOW,
  prStatus,
  question,
  queuedMessage,
  repo,
  review,
  session,
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

const apply = (state: State, e: HarnessEvent) => reduce(state, { type: "event", event: e });

describe("reduce", () => {
  it("loads snapshots, keeping only pending approvals", () => {
    const state = loaded();

    expect(state.auth).toBe("ready");
    expect(Object.keys(state.sessions)).toEqual(["s1", "s2"]);
    expect(Object.keys(state.approvals)).toEqual(["q1"]);
    expect(reduce(state, { type: "auth", auth: "unpaired" }).auth).toBe("unpaired");
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
});
