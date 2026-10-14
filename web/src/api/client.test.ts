import { describe, expect, it, vi } from "vitest";
import { agentDefaults, notificationSettings } from "../test/fixtures.ts";
import { ApiError, HttpApi, OPEN_ELSEWHERE, type Api } from "./client.ts";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function setup(status = 200, body: unknown = { ok: true }) {
  const fetchFn = vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(status, body)));
  return { api: new HttpApi(fetchFn), fetchFn };
}

type Call = [string, (api: Api) => Promise<unknown>, string, string, unknown];

const file = new File(["hi"], "note.txt", { type: "text/plain" });

const calls: Call[] = [
  ["repos", (a) => a.repos(), "GET", "/api/repos", undefined],
  ["sessions", (a) => a.sessions(false), "GET", "/api/sessions?archived=false", undefined],
  ["archived", (a) => a.sessions(true), "GET", "/api/sessions?archived=true", undefined],
  ["session", (a) => a.session("s/1"), "GET", "/api/sessions/s%2F1", undefined],
  ["events", (a) => a.sessionEvents("s1"), "GET", "/api/sessions/s1/events", undefined],
  [
    "create",
    (a) => a.createSession({ repo: "r", prompt: "p" }),
    "POST",
    "/api/sessions",
    { repo: "r", prompt: "p" },
  ],
  [
    "send",
    (a) => a.sendMessage("s1", "hi", ["a1"]),
    "POST",
    "/api/sessions/s1/messages",
    { text: "hi", attachment_ids: ["a1"] },
  ],
  [
    "send interrupting",
    (a) => a.sendMessage("s1", "nudge", [], true),
    "POST",
    "/api/sessions/s1/messages",
    { text: "nudge", attachment_ids: [], interrupt: true },
  ],
  [
    "search",
    (a) => a.search("login bug&x"),
    "GET",
    "/api/search?q=login%20bug%26x&limit=50",
    undefined,
  ],
  ["interrupt", (a) => a.interrupt("s1"), "POST", "/api/sessions/s1/interrupt", undefined],
  [
    "cancel queued",
    (a) => a.cancelQueued("s1", "m/1"),
    "DELETE",
    "/api/sessions/s1/queue/m%2F1",
    undefined,
  ],
  [
    "session commands",
    (a) => a.sessionCommands("s/1"),
    "GET",
    "/api/sessions/s%2F1/commands",
    undefined,
  ],
  [
    "repo commands",
    (a) => a.repoCommands("todo ui"),
    "GET",
    "/api/repos/todo%20ui/commands",
    undefined,
  ],
  [
    "files",
    (a) => a.files("s1", "src/a b&c"),
    "GET",
    "/api/sessions/s1/files?q=src%2Fa%20b%26c",
    undefined,
  ],
  [
    "update",
    (a) => a.updateSession("s1", { pinned: true }),
    "PATCH",
    "/api/sessions/s1",
    { pinned: true },
  ],
  ["purge", (a) => a.deleteSession("s1"), "DELETE", "/api/sessions/s1?purge=true", undefined],
  ["claude chats", (a) => a.claudeChats(), "GET", "/api/claude-chats", undefined],
  [
    "automated claude chats too",
    (a) => a.claudeChats(true),
    "GET",
    "/api/claude-chats?include_automated=true",
    undefined,
  ],
  [
    "claude chat events",
    (a) => a.claudeChatEvents("c/1"),
    "GET",
    "/api/claude-chats/c%2F1/events",
    undefined,
  ],
  ["adopt", (a) => a.adoptClaudeChat("c1"), "POST", "/api/claude-chats/c1/adopt", undefined],
  [
    "archive a claude chat",
    (a) => a.setClaudeChatArchived("c/1", true),
    "PUT",
    "/api/claude-chats/c%2F1/archived",
    { archived: true },
  ],
  ["approvals", (a) => a.approvals(), "GET", "/api/approvals?status=pending", undefined],
  [
    "resolve",
    (a) => a.resolveApproval("q1", { behavior: "allow" }),
    "POST",
    "/api/approvals/q1/resolve",
    { behavior: "allow" },
  ],
  [
    "keep planning",
    (a) => a.resolveApproval("q4", { decision: "keep_planning", message: "Smaller steps" }),
    "POST",
    "/api/approvals/q4/resolve",
    { decision: "keep_planning", message: "Smaller steps" },
  ],
  ["diff", (a) => a.diff("s1"), "GET", "/api/sessions/s1/diff", undefined],
  [
    "approve",
    (a) => a.approve("s1", { commit_message: "m", expected_fingerprint: "f1" }),
    "POST",
    "/api/sessions/s1/approve",
    { commit_message: "m", expected_fingerprint: "f1" },
  ],
  ["reject", (a) => a.reject("s1"), "POST", "/api/sessions/s1/reject", undefined],
  [
    "feedback",
    (a) => a.feedback("s1", "more"),
    "POST",
    "/api/sessions/s1/feedback",
    { text: "more" },
  ],
  [
    "merge",
    (a) => a.merge("s1", { method: "squash" }),
    "POST",
    "/api/sessions/s1/merge",
    { method: "squash" },
  ],
  ["connectors", (a) => a.connectors(), "GET", "/api/connectors", undefined],
  ["month", (a) => a.usageMonth(2026, 10), "GET", "/api/usage/month?year=2026&month=10", undefined],
  ["limits", (a) => a.usageLimits(), "GET", "/api/usage/limits", undefined],
  ["refresh usage", (a) => a.refreshUsage(), "POST", "/api/usage/refresh", undefined],
  [
    "visibility",
    (a) => a.reportVisibility(true),
    "POST",
    "/api/clients/visibility",
    { visible: true, client: "pwa" },
  ],
  ["vapid key", (a) => a.vapidKey(), "GET", "/api/push/vapid-key", undefined],
  [
    "subscribe",
    (a) => a.subscribePush({ endpoint: "https://p/1", keys: { p256dh: "k", auth: "a" } }),
    "POST",
    "/api/push/subscribe",
    { endpoint: "https://p/1", keys: { p256dh: "k", auth: "a" } },
  ],
  [
    "unsubscribe",
    (a) => a.unsubscribePush("https://p/1"),
    "DELETE",
    "/api/push/subscribe",
    { endpoint: "https://p/1" },
  ],
  ["test push", (a) => a.testPush(), "POST", "/api/push/test", undefined],
  [
    "notification settings",
    (a) => a.notificationSettings(),
    "GET",
    "/api/notifications/settings",
    undefined,
  ],
  [
    "save notification settings",
    (a) => a.saveNotificationSettings(notificationSettings()),
    "PUT",
    "/api/notifications/settings",
    notificationSettings(),
  ],
  ["models", (a) => a.models(), "GET", "/api/models", undefined],
  ["account", (a) => a.account(), "GET", "/api/account", undefined],
  ["agent defaults", (a) => a.agentDefaults(), "GET", "/api/agents/defaults", undefined],
  [
    "save agent defaults",
    (a) => a.saveAgentDefaults(agentDefaults({ model: "opus" })),
    "PUT",
    "/api/agents/defaults",
    agentDefaults({ model: "opus" }),
  ],
  [
    "remove repo",
    (a) => a.removeRepo("todo ui", false),
    "DELETE",
    "/api/repos/todo%20ui?purge_sessions=false",
    undefined,
  ],
  [
    "remove repo and its chats",
    (a) => a.removeRepo("todo-ui", true),
    "DELETE",
    "/api/repos/todo-ui?purge_sessions=true",
    undefined,
  ],
  [
    "worktree default",
    (a) => a.updateRepo("todo-ui", { default: false }),
    "PATCH",
    "/api/repos/todo-ui",
    { default: false },
  ],
  [
    "links and setup",
    (a) => a.updateRepo("todo-ui", { link: [".env"], setup: ["npm ci"] }),
    "PATCH",
    "/api/repos/todo-ui",
    { link: [".env"], setup: ["npm ci"] },
  ],
  ["ci feedback", (a) => a.ciFeedback("s1"), "POST", "/api/sessions/s1/ci-feedback", undefined],
  [
    "rewind preview",
    (a) => a.rewindPreview("s1", 42),
    "GET",
    "/api/sessions/s1/rewind?message=42",
    undefined,
  ],
  ["rewind", (a) => a.rewind("s1", 42), "POST", "/api/sessions/s1/rewind", { message: 42 }],
  [
    "redeem",
    (a) => a.redeem("ABCD2345", "iPhone"),
    "POST",
    "/api/pairing/redeem",
    { code: "ABCD2345", device_name: "iPhone" },
  ],
  ["pixies", (a) => a.pixies(), "GET", "/api/pixies", undefined],
  [
    "createPixie",
    (a) => a.createPixie({ name: "Tester" }),
    "POST",
    "/api/pixies",
    { name: "Tester" },
  ],
  [
    "updatePixie",
    (a) => a.updatePixie("p 1", { mascot: "ghost" }),
    "PATCH",
    "/api/pixies/p%201",
    { mascot: "ghost" },
  ],
  ["deletePixie", (a) => a.deletePixie("p1"), "DELETE", "/api/pixies/p1", undefined],
  [
    "reorderPixies",
    (a) => a.reorderPixies(["p2", "p1"]),
    "PUT",
    "/api/pixies/order",
    { ids: ["p2", "p1"] },
  ],
  [
    "sendToPixie",
    (a) => a.sendToPixie("p1", "hi"),
    "POST",
    "/api/pixies/p1/messages",
    { text: "hi" },
  ],
  ["resetPixie", (a) => a.resetPixie("p1"), "POST", "/api/pixies/p1/reset", undefined],
  [
    "pixieFile",
    (a) => a.pixieFile("p1", "notes/a"),
    "GET",
    "/api/pixies/p1/files/notes/a",
    undefined,
  ],
  [
    "savePixieFile",
    (a) => a.savePixieFile("p1", "soul", "x", "h"),
    "PUT",
    "/api/pixies/p1/files/soul",
    { text: "x", hash: "h" },
  ],
  ["pixieNotes", (a) => a.pixieNotes("p1"), "GET", "/api/pixies/p1/notes", undefined],
  [
    "searchPixie",
    (a) => a.searchPixie("p1", "a b"),
    "GET",
    "/api/pixies/p1/search?q=a%20b",
    undefined,
  ],
  [
    "duplicatePixie",
    (a) => a.duplicatePixie("p 1"),
    "POST",
    "/api/pixies/p%201/duplicate",
    undefined,
  ],
  ["teams", (a) => a.teams(), "GET", "/api/pixie-teams", undefined],
  [
    "createTeam",
    (a) => a.createTeam({ name: "QA", handle: "qa" }),
    "POST",
    "/api/pixie-teams",
    { name: "QA", handle: "qa" },
  ],
  [
    "updateTeam",
    (a) => a.updateTeam("t 1", { leader_id: "p1" }),
    "PATCH",
    "/api/pixie-teams/t%201",
    { leader_id: "p1" },
  ],
  ["deleteTeam", (a) => a.deleteTeam("t1"), "DELETE", "/api/pixie-teams/t1", undefined],
];

describe("HttpApi", () => {
  it.each(calls)("%s sends the right request", async (_name, call, method, path, body) => {
    const { api, fetchFn } = setup();

    await expect(call(api)).resolves.toEqual({ ok: true });

    const [url, init] = fetchFn.mock.calls[0] ?? [];
    expect(url).toBe(path);
    expect(init?.method).toBe(method);
    expect(init?.credentials).toBe("same-origin");
    if (body === undefined) {
      expect(init?.body).toBeUndefined();
    } else {
      expect(JSON.parse(init?.body as string)).toEqual(body);
      expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    }
  });

  it("returns null for empty responses", async () => {
    const fetchFn = vi.fn<typeof fetch>(() => Promise.resolve(new Response(null, { status: 204 })));

    await expect(new HttpApi(fetchFn).deleteSession("s1")).resolves.toBeNull();
  });

  it("uploads attachments as multipart form data", async () => {
    const { api, fetchFn } = setup(201, { id: "a1" });

    await expect(api.uploadAttachment(file)).resolves.toEqual({ id: "a1" });

    const [url, init] = fetchFn.mock.calls[0] ?? [];
    expect(url).toBe("/api/attachments");
    expect(init?.method).toBe("POST");
    const form = init?.body as FormData;
    expect((form.get("file") as File).name).toBe("note.txt");
  });

  it("raises the daemon's detail message with the status", async () => {
    const { api } = setup(409, { detail: "session is working" });

    const error = await api.repos().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, message: "session is working", code: null });
  });

  it("keeps the daemon's reason code", async () => {
    const { api } = setup(409, { detail: "Open in Claude Code", code: OPEN_ELSEWHERE });

    await expect(api.sendMessage("s1", "hi", [])).rejects.toMatchObject({
      message: "Open in Claude Code",
      code: "open_in_claude_code",
    });
  });

  it("keeps the whole refusal for the fields some carry", async () => {
    const body = {
      detail: "origin now pushes to x",
      code: "remote_changed",
      remote_urls: ["https://github.com/me/x.git"],
      confirmed_url: "https://github.com/me/y.git",
    };
    const { api } = setup(409, body);

    await expect(
      api.approve("s1", { commit_message: "m", expected_fingerprint: "f1" }),
    ).rejects.toMatchObject({
      code: "remote_changed",
      data: body,
    });
    await expect(
      new HttpApi(() => Promise.resolve(jsonResponse(409, ["x"]))).repos(),
    ).rejects.toMatchObject({ data: {} });
  });

  it("keeps the whole body of a stale-file refusal", async () => {
    const body = { detail: "soul changed", code: "stale_file", text: "Theirs", hash: "h2" };
    const { api } = setup(409, body);

    await expect(api.savePixieFile("p1", "soul", "Mine", "h1")).rejects.toMatchObject({
      code: "stale_file",
      data: body,
    });
    expect(new ApiError(500, "x").data).toEqual({});
  });

  it.each([
    [jsonResponse(422, { detail: [{ msg: "bad" }] })],
    [new Response("<html>", { status: 502 })],
  ])("falls back to a generic message", async (response) => {
    const api = new HttpApi(() => Promise.resolve(response));

    await expect(api.repos()).rejects.toMatchObject({
      status: response.status,
      message: `Request failed (${String(response.status)})`,
    });
  });

  it("marks unauthenticated responses", async () => {
    const { api } = setup(401, { detail: "not authenticated" });

    await expect(api.repos()).rejects.toMatchObject({ unauthorized: true });
  });

  it("uses the global fetch by default", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, []));

    await expect(new HttpApi().repos()).resolves.toEqual([]);

    expect(spy).toHaveBeenCalledOnce();
    spy.mockRestore();
  });
});
