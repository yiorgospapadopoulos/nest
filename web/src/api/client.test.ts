import { describe, expect, it, vi } from "vitest";
import { agentDefaults, notificationSettings, pixieDefaults } from "../test/fixtures.ts";
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
  ["repo", (a) => a.repo("cv page"), "GET", "/api/repos/cv%20page", undefined],
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
    "stop task",
    (a) => a.stopTask("s/1", "toolu 1"),
    "POST",
    "/api/sessions/s%2F1/tasks/toolu%201/stop",
    undefined,
  ],
  [
    "cancel queued",
    (a) => a.cancelQueued("s1", "m/1"),
    "DELETE",
    "/api/sessions/s1/queue/m%2F1",
    undefined,
  ],
  [
    "send a pending message now",
    (a) => a.sendNow("s1", "m/1"),
    "POST",
    "/api/sessions/s1/queue/m%2F1/send-now",
    undefined,
  ],
  [
    "resume after the usage limit",
    (a) => a.resumeLimit("s/1"),
    "POST",
    "/api/sessions/s%2F1/limit/resume",
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
    (a) => a.repoCommands("cv page"),
    "GET",
    "/api/repos/cv%20page/commands",
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
  [
    "usage period",
    (a) => a.usagePeriod("week", "2026-10-17"),
    "GET",
    "/api/usage/period?unit=week&date=2026-10-17",
    undefined,
  ],
  ["limits", (a) => a.usageLimits(), "GET", "/api/usage/limits", undefined],
  ["refresh usage", (a) => a.refreshUsage(), "POST", "/api/usage/refresh", undefined],
  ["restart", (a) => a.restartService(), "POST", "/api/service/restart", undefined],
  ["health", (a) => a.health(), "GET", "/api/health", undefined],
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
    (a) => a.removeRepo("cv page", false),
    "DELETE",
    "/api/repos/cv%20page?purge_sessions=false",
    undefined,
  ],
  [
    "remove repo and its chats",
    (a) => a.removeRepo("cv-page", true),
    "DELETE",
    "/api/repos/cv-page?purge_sessions=true",
    undefined,
  ],
  [
    "worktree default",
    (a) => a.updateRepo("cv-page", { default: false }),
    "PATCH",
    "/api/repos/cv-page",
    { default: false },
  ],
  [
    "links and setup",
    (a) => a.updateRepo("cv-page", { link: [".env"], setup: ["npm ci"] }),
    "PATCH",
    "/api/repos/cv-page",
    { link: [".env"], setup: ["npm ci"] },
  ],
  ["ci feedback", (a) => a.ciFeedback("s1"), "POST", "/api/sessions/s1/ci-feedback", undefined],
  [
    "rewind preview",
    (a) => a.rewindPreview("s1", 42),
    "GET",
    "/api/sessions/s1/rewind?message=42&restore=code",
    undefined,
  ],
  [
    "conversation rewind preview",
    (a) => a.rewindPreview("s1", 42, "conversation"),
    "GET",
    "/api/sessions/s1/rewind?message=42&restore=conversation",
    undefined,
  ],
  [
    "rewind",
    (a) => a.rewind("s1", 42),
    "POST",
    "/api/sessions/s1/rewind",
    { message: 42, restore: "code" },
  ],
  [
    "rewind both",
    (a) => a.rewind("s1", 42, "both"),
    "POST",
    "/api/sessions/s1/rewind",
    { message: 42, restore: "both" },
  ],
  ["fork", (a) => a.fork("s/1", 42), "POST", "/api/sessions/s%2F1/fork", { message: 42 }],
  [
    "shell",
    (a) => a.shell("s/1", "git status"),
    "POST",
    "/api/sessions/s%2F1/shell",
    { command: "git status" },
  ],
  [
    "remember",
    (a) => a.remember("s1", "Run make check", "project"),
    "POST",
    "/api/sessions/s1/memory",
    { text: "Run make check", scope: "project" },
  ],
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
  ["pixieSkills", (a) => a.pixieSkills(), "GET", "/api/pixies/skills", undefined],
  ["pixieActivity", (a) => a.pixieActivity("p 1"), "GET", "/api/pixies/p%201/activity", undefined],
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
  ["habits", (a) => a.habits("p 1"), "GET", "/api/pixies/p%201/habits", undefined],
  [
    "createHabit",
    (a) => a.createHabit("p1", { name: "Check", prompt: "Look", triggers: ["stuck"] }),
    "POST",
    "/api/pixies/p1/habits",
    { name: "Check", prompt: "Look", triggers: ["stuck"] },
  ],
  [
    "updateHabit",
    (a) => a.updateHabit("p1", "h 1", { enabled: false }),
    "PATCH",
    "/api/pixies/p1/habits/h%201",
    { enabled: false },
  ],
  [
    "deleteHabit",
    (a) => a.deleteHabit("p1", "h1"),
    "DELETE",
    "/api/pixies/p1/habits/h1",
    undefined,
  ],
  ["runHabit", (a) => a.runHabit("p1", "h1"), "POST", "/api/pixies/p1/habits/h1/run", undefined],
  ["habitRuns", (a) => a.habitRuns("p1", "h1"), "GET", "/api/pixies/p1/habits/h1/runs", undefined],
  [
    "pixieReports",
    (a) => a.pixieReports(false),
    "GET",
    "/api/pixie-reports?unread=false",
    undefined,
  ],
  ["readReport", (a) => a.readReport("r 1"), "POST", "/api/pixie-reports/r%201/read", undefined],
  [
    "readPixieReports",
    (a) => a.readPixieReports("p1"),
    "POST",
    "/api/pixies/p1/reports/read",
    undefined,
  ],
  ["pixieGroups", (a) => a.pixieGroups(), "GET", "/api/pixie-groups", undefined],
  ["goals", (a) => a.goals("cv page"), "GET", "/api/goals?repo=cv%20page", undefined],
  [
    "sendAway",
    (a) => a.sendAway("s 1", { team_id: "t1" }),
    "POST",
    "/api/sessions/s%201/pixies/send-away",
    { team_id: "t1" },
  ],
  [
    "pixieCalls",
    (a) => a.pixieCalls("s 1", "p/1"),
    "GET",
    "/api/sessions/s%201/pixies/p%2F1/calls",
    undefined,
  ],
  [
    "agentTranscript",
    (a) => a.agentTranscript("s 1", "toolu/1"),
    "GET",
    "/api/sessions/s%201/agents/toolu%2F1/transcript",
    undefined,
  ],
  ["branches", (a) => a.branches("cv page"), "GET", "/api/repos/cv%20page/branches", undefined],
  [
    "default branch and remote",
    (a) => a.updateRepo("cv-page", { default_branch: "dev", remote_url: null }),
    "PATCH",
    "/api/repos/cv-page",
    { default_branch: "dev", remote_url: null },
  ],
  ["storage", (a) => a.storage(), "GET", "/api/storage", undefined],
  ["storage settings", (a) => a.storageSettings(), "GET", "/api/storage/settings", undefined],
  [
    "save storage settings",
    (a) => a.saveStorageSettings({ archive_after_days: 30 }),
    "PUT",
    "/api/storage/settings",
    { archive_after_days: 30 },
  ],
  [
    "large attachments",
    (a) => a.largeAttachments(20),
    "GET",
    "/api/storage/attachments?limit=20",
    undefined,
  ],
  [
    "delete attachment",
    (a) => a.deleteAttachment("a/1"),
    "DELETE",
    "/api/attachments/a%2F1",
    undefined,
  ],
  ["rebuild search", (a) => a.rebuildSearch(), "POST", "/api/search/rebuild", undefined],
  ["usage settings", (a) => a.usageSettings(), "GET", "/api/usage/settings", undefined],
  [
    "save usage settings",
    (a) => a.saveUsageSettings({ refresh_minutes: 5, warn_percent: null, warn_notify: true }),
    "PUT",
    "/api/usage/settings",
    { refresh_minutes: 5, warn_percent: null, warn_notify: true },
  ],
  ["stuck settings", (a) => a.stuckSettings(), "GET", "/api/stuck/settings", undefined],
  [
    "save stuck settings",
    (a) =>
      a.saveStuckSettings({
        waiting_minutes: 1,
        silent_minutes: 2,
        repeated_calls: 3,
        turn_minutes: 4,
      }),
    "PUT",
    "/api/stuck/settings",
    { waiting_minutes: 1, silent_minutes: 2, repeated_calls: 3, turn_minutes: 4 },
  ],
  ["pixie defaults", (a) => a.pixieDefaults(), "GET", "/api/pixie-settings", undefined],
  [
    "save pixie defaults",
    (a) => a.savePixieDefaults(pixieDefaults()),
    "PUT",
    "/api/pixie-settings",
    pixieDefaults(),
  ],
  ["github", (a) => a.github(), "GET", "/api/accounts/github", undefined],
  ["check github", (a) => a.checkGithub(), "POST", "/api/accounts/github/check", undefined],
  ["claude account", (a) => a.claudeAccount(), "GET", "/api/accounts/claude", undefined],
  ["claude login", (a) => a.claudeLogin(), "POST", "/api/accounts/claude/login", undefined],
  ["claude logout", (a) => a.claudeLogout(), "POST", "/api/accounts/claude/logout", undefined],
  ["claude code", (a) => a.claudeCode(), "GET", "/api/claude-code", undefined],
  [
    "install claude code",
    (a) => a.installClaudeCode(),
    "POST",
    "/api/claude-code/install",
    undefined,
  ],
  ["devices", (a) => a.devices(), "GET", "/api/devices", undefined],
  ["revoke device", (a) => a.revokeDevice("d/1"), "DELETE", "/api/devices/d%2F1", undefined],
  ["pairing code", (a) => a.pairingCode(), "POST", "/api/pairing/codes", undefined],
  ["plugins", (a) => a.plugins(), "GET", "/api/extensions/plugins", undefined],
  ["skills", (a) => a.skills(), "GET", "/api/extensions/skills", undefined],
  ["marketplaces", (a) => a.marketplaces(), "GET", "/api/extensions/marketplaces", undefined],
  [
    "add marketplace",
    (a) => a.addMarketplace("me/plugins"),
    "POST",
    "/api/extensions/marketplaces",
    { source: "me/plugins" },
  ],
  [
    "remove marketplace",
    (a) => a.removeMarketplace("my market"),
    "DELETE",
    "/api/extensions/marketplaces/my%20market",
    undefined,
  ],
  ["available plugins", (a) => a.availablePlugins(), "GET", "/api/extensions/available", undefined],
  [
    "plugin details",
    (a) => a.pluginDetails("pdf@official"),
    "GET",
    "/api/extensions/plugins/pdf%40official/details",
    undefined,
  ],
  [
    "install plugin",
    (a) => a.installPlugin("pdf@official"),
    "POST",
    "/api/extensions/plugins/pdf%40official/install",
    undefined,
  ],
  [
    "uninstall plugin",
    (a) => a.uninstallPlugin("pdf@official"),
    "POST",
    "/api/extensions/plugins/pdf%40official/uninstall",
    undefined,
  ],
  [
    "enable plugin",
    (a) => a.setPluginEnabled("pdf@official", false),
    "PUT",
    "/api/extensions/plugins/pdf%40official/enabled",
    { enabled: false },
  ],
  ["artifacts", (a) => a.artifacts({}), "GET", "/api/artifacts", undefined],
  [
    "artifacts",
    (a) => a.artifacts({ session_id: "s1", repo: "cv page" }),
    "GET",
    "/api/artifacts?session_id=s1&repo=cv+page",
    undefined,
  ],
  [
    "artifacts",
    (a) => a.artifacts({ pixie_id: "p1" }),
    "GET",
    "/api/artifacts?pixie_id=p1",
    undefined,
  ],
  ["artifactsUnseen", (a) => a.artifactsUnseen(), "GET", "/api/artifacts/unseen", undefined],
  ["artifact", (a) => a.artifact("a/1"), "GET", "/api/artifacts/a%2F1", undefined],
  [
    "artifactVersion",
    (a) => a.artifactVersion("a1", 2),
    "GET",
    "/api/artifacts/a1/versions/2",
    undefined,
  ],
  [
    "markArtifactSeen",
    (a) => a.markArtifactSeen("a1"),
    "POST",
    "/api/artifacts/a1/seen",
    undefined,
  ],
  ["deleteArtifact", (a) => a.deleteArtifact("a1"), "DELETE", "/api/artifacts/a1", undefined],
  [
    "artifactStorage",
    (a) => a.artifactStorage("a/1"),
    "GET",
    "/api/artifacts/a%2F1/storage",
    undefined,
  ],
  [
    "writeArtifactStorage",
    (a) => a.writeArtifactStorage("a1", { set: { k: "v" }, remove: ["x"] }),
    "POST",
    "/api/artifacts/a1/storage",
    { set: { k: "v" }, remove: ["x"] },
  ],
  [
    "clearArtifactStorage",
    (a) => a.clearArtifactStorage("a1"),
    "DELETE",
    "/api/artifacts/a1/storage",
    undefined,
  ],
  ["askStatus", (a) => a.askStatus("a1"), "GET", "/api/artifacts/a1/ask", undefined],
  [
    "askArtifact",
    (a) => a.askArtifact("a1", { prompt: "Hi", system: "Brief" }),
    "POST",
    "/api/artifacts/a1/ask",
    { prompt: "Hi", system: "Brief" },
  ],
  [
    "saveArtifactVersion",
    (a) => a.saveArtifactVersion("a/1", { content: "# New", base_version: 3 }),
    "POST",
    "/api/artifacts/a%2F1/versions",
    { content: "# New", base_version: 3 },
  ],
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

  it("reads an attachment as data, with the device's credentials", async () => {
    const fetchFn = vi.fn<typeof fetch>(() =>
      Promise.resolve(new Response("png", { headers: { "Content-Type": "image/png" } })),
    );
    const api = new HttpApi(fetchFn);

    const blob = await api.attachment("a/1");

    expect(await blob.text()).toBe("png");
    const [url, init] = fetchFn.mock.calls[0] ?? [];
    expect(url).toBe("/api/attachments/a%2F1");
    expect(init?.credentials).toBe("same-origin");
  });

  it("raises an attachment the Mac does not have", async () => {
    const { api } = setup(404, { detail: "unknown attachment 'x'" });

    await expect(api.attachment("x")).rejects.toMatchObject({
      status: 404,
      message: "unknown attachment 'x'",
    });
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
