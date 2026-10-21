import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client.ts";
import { fakeApi } from "../test/fakeApi.ts";
import {
  artifact,
  artifactContent,
  artifactDetail,
  callWork,
  detail,
  event,
  groupEntry,
  pixie,
  session,
  team,
  usagePeriod,
  agentDefaults,
  claudeProvider,
  codexAccount,
  codexProvider,
  engineLimits,
  mergeApproval,
  modelList,
} from "../test/fixtures.ts";
import {
  FOLDED_TEAMS_KEY,
  loadFoldedTeams,
  loadUsageBarHidden,
  USAGE_BAR_HIDDEN_KEY,
} from "./devicePrefs.ts";
import { createActions } from "./actions.ts";
import type { Action } from "./state.ts";

function setup() {
  const api = fakeApi();
  const dispatched: Action[] = [];
  const actions = createActions(
    api,
    (a) => dispatched.push(a),
    () => localStorage,
  );
  return { api, dispatched, actions };
}

describe("pixie actions", () => {
  it("reports refused habit changes and changes nothing (B42)", async () => {
    const { api, dispatched, actions } = setup();
    api.updateHabit.mockRejectedValueOnce(new Error("no"));
    api.deleteHabit.mockRejectedValueOnce(new Error("no"));
    api.runHabit.mockRejectedValueOnce(new Error("no"));
    expect(await actions.updateHabit("p1", "h1", { enabled: false })).toBe(false);
    expect(await actions.deleteHabit("p1", "h1")).toBe(false);
    expect(await actions.runHabit("p1", "h1")).toBe(false);
    expect(dispatched.map((a) => a.type)).toEqual(["toast", "toast", "toast"]);
  });

  it("loads pixies, teams and their reports, each quietly on failure", async () => {
    const { api, dispatched, actions } = setup();
    api.pixies.mockResolvedValueOnce([pixie()]);
    api.teams.mockResolvedValueOnce([team()]);
    await actions.loadPixies();
    expect(dispatched).toEqual([
      { type: "pixies", pixies: [pixie()] },
      { type: "teams", teams: [team()] },
      { type: "reports", reports: [] },
    ]);
    api.pixies.mockRejectedValueOnce(new Error("down"));
    api.teams.mockRejectedValueOnce(new Error("down"));
    api.pixieReports.mockRejectedValueOnce(new Error("down"));
    await actions.loadPixies();
    expect(dispatched).toHaveLength(3);
  });

  it("creates, renames, leads and deletes teams", async () => {
    const { api, dispatched, actions } = setup();
    expect(await actions.createTeam("QA")).toEqual(team());
    expect(api.createTeam).toHaveBeenCalledWith({ name: "QA" });
    expect(await actions.updateTeam("t1", { leader_id: "p1" })).toBe(true);
    expect(await actions.deleteTeam("t1")).toBe(true);
    expect(dispatched.map((a) => a.type)).toEqual(["team", "team", "teamRemoved"]);
    api.createTeam.mockRejectedValueOnce(new Error("no"));
    api.updateTeam.mockRejectedValueOnce(new ApiError(409, "not a member", "leader_not_member"));
    api.deleteTeam.mockRejectedValueOnce(new Error("no"));
    expect(await actions.createTeam("QA")).toBeNull();
    expect(await actions.updateTeam("t1", { leader_id: "p9" })).toBe(false);
    expect(await actions.deleteTeam("t1")).toBe(false);
    expect(dispatched.at(-1)).toMatchObject({ type: "toast", toast: { tone: "error" } });
  });

  it("sets a team handle, returning why the Mac refused it", async () => {
    const { api, dispatched, actions } = setup();
    expect(await actions.setTeamHandle("t1", "qa")).toBeNull();
    expect(dispatched[0]).toMatchObject({ type: "team" });
    api.updateTeam.mockRejectedValueOnce(new ApiError(409, "taken"));
    expect(await actions.setTeamHandle("t1", "x")).toBe("taken");
    api.updateTeam.mockRejectedValueOnce(new ApiError(422, "bad handle"));
    expect(await actions.setTeamHandle("t1", "X")).toBe("bad handle");
    api.updateTeam.mockRejectedValueOnce(new Error("down"));
    expect(await actions.setTeamHandle("t1", "y")).toBeNull();
    expect(dispatched.at(-1)).toMatchObject({ type: "toast", toast: { text: "down" } });
  });

  it("duplicates a pixie", async () => {
    const { api, dispatched, actions } = setup();
    const copy = pixie({ id: "p2", name: "Tester 2", slug: "tester-2" });
    api.duplicatePixie.mockResolvedValueOnce(copy);
    expect(await actions.duplicatePixie("p1")).toEqual(copy);
    expect(dispatched[0]).toEqual({ type: "pixie", pixie: copy });
    api.duplicatePixie.mockRejectedValueOnce(new Error("no"));
    expect(await actions.duplicatePixie("p1")).toBeNull();
  });

  it("remembers folded teams on this device, and copes without storage", () => {
    localStorage.removeItem(FOLDED_TEAMS_KEY);
    const { dispatched, actions } = setup();
    actions.setTeamFolded("t1", true);
    actions.setTeamFolded("t2", true);
    actions.setTeamFolded("t1", false);
    expect(dispatched).toEqual([
      { type: "teamFolded", id: "t1", folded: true },
      { type: "teamFolded", id: "t2", folded: true },
      { type: "teamFolded", id: "t1", folded: false },
    ]);
    expect(loadFoldedTeams(() => localStorage)).toEqual(["t2"]);

    const broken = () => {
      throw new Error("blocked");
    };
    const offline = createActions(fakeApi(), () => undefined, broken);
    offline.setTeamFolded("t3", true);
    expect(loadFoldedTeams(broken)).toEqual([]);
    localStorage.setItem(FOLDED_TEAMS_KEY, "{not json");
    expect(loadFoldedTeams(() => localStorage)).toEqual([]);
    localStorage.setItem(FOLDED_TEAMS_KEY, JSON.stringify({ a: 1 }));
    expect(loadFoldedTeams(() => localStorage)).toEqual([]);
    localStorage.setItem(FOLDED_TEAMS_KEY, JSON.stringify(["a", 2]));
    expect(loadFoldedTeams(() => localStorage)).toEqual(["a"]);
    localStorage.removeItem(FOLDED_TEAMS_KEY);
  });

  it("creates a pixie and shows a 409 as a toast", async () => {
    const { api, dispatched, actions } = setup();
    expect(await actions.createPixie({ name: "Tester" })).toEqual(pixie());
    expect(dispatched[0]).toEqual({ type: "pixie", pixie: pixie() });
    api.createPixie.mockRejectedValueOnce(new ApiError(409, "That slug is taken"));
    expect(await actions.createPixie({ name: "Tester" })).toBeNull();
    expect(dispatched.at(-1)).toMatchObject({ type: "toast", toast: { tone: "error" } });
  });

  it("updates, resets and deletes", async () => {
    const { api, dispatched, actions } = setup();
    expect(await actions.updatePixie("p1", { name: "New" })).toBe(true);
    expect(await actions.resetPixie("p1")).toBe(true);
    expect(await actions.deletePixie("p1")).toBe(true);
    expect(dispatched.map((a) => a.type)).toEqual(["pixie", "pixie", "pixieRemoved"]);
    api.updatePixie.mockRejectedValueOnce(new Error("no"));
    api.resetPixie.mockRejectedValueOnce(new Error("no"));
    api.deletePixie.mockRejectedValueOnce(new Error("no"));
    expect(await actions.updatePixie("p1", {})).toBe(false);
    expect(await actions.resetPixie("p1")).toBe(false);
    expect(await actions.deletePixie("p1")).toBe(false);
  });

  it("sends to a pixie", async () => {
    const { api, dispatched, actions } = setup();
    const sent = session({ pixie_id: "p1", repo: "pixie:p1" });
    api.sendToPixie.mockResolvedValueOnce(sent);
    expect(await actions.sendToPixie("p1", "hi")).toEqual(sent);
    expect(dispatched[0]).toEqual({ type: "session", session: sent });
    api.sendToPixie.mockRejectedValueOnce(new Error("no"));
    expect(await actions.sendToPixie("p1", "hi")).toBeNull();
    vi.clearAllMocks();
  });

  it("loads the rest and stays online when pixies cannot load", async () => {
    const { api, dispatched, actions } = setup();
    api.pixies.mockRejectedValueOnce(new Error("no pixies"));
    await actions.load();
    expect(dispatched.map((a) => a.type)).toEqual([
      "loaded",
      "claudeChats",
      "unseenArtifacts",
      "teams",
      "reports",
      "pixieGroups",
    ]);
  });

  it("reads a pixie file, empty when it does not exist", async () => {
    const { api, dispatched, actions } = setup();
    api.pixieFile.mockResolvedValueOnce({ text: "Hi", hash: "h" });
    expect(await actions.readPixieFile("p1", "soul")).toEqual({ text: "Hi", hash: "h" });
    api.pixieFile.mockRejectedValueOnce(new ApiError(404, "gone"));
    expect(await actions.readPixieFile("p1", "soul")).toEqual({ text: "", hash: null });
    api.pixieFile.mockRejectedValueOnce(new Error("down"));
    expect(await actions.readPixieFile("p1", "soul")).toBeNull();
    expect(dispatched.at(-1)).toMatchObject({ type: "toast", toast: { text: "down" } });
  });

  it("saves a pixie file and returns the current one when it is stale", async () => {
    const { api, actions } = setup();
    api.savePixieFile.mockResolvedValueOnce({ text: "Mine", hash: "h2" });
    expect(await actions.savePixieFile("p1", "soul", "Mine", "h1")).toEqual({
      saved: { text: "Mine", hash: "h2" },
    });
    api.savePixieFile.mockRejectedValueOnce(
      new ApiError(409, "changed", "stale_file", { text: "Theirs", hash: "h3" }),
    );
    expect(await actions.savePixieFile("p1", "soul", "Mine", "h1")).toEqual({
      stale: { text: "Theirs", hash: "h3" },
    });
    // A body without the file reads as empty.
    api.savePixieFile.mockRejectedValueOnce(new ApiError(409, "changed", "stale_file"));
    expect(await actions.savePixieFile("p1", "soul", "Mine", "h1")).toEqual({
      stale: { text: "", hash: null },
    });
    api.savePixieFile.mockRejectedValueOnce(
      new ApiError(409, "changed", "stale_file", { text: 1 }),
    );
    expect(await actions.savePixieFile("p1", "soul", "Mine", "h1")).toEqual({
      stale: { text: "", hash: null },
    });
    api.savePixieFile.mockRejectedValueOnce(new Error("down"));
    expect(await actions.savePixieFile("p1", "soul", "Mine", "h1")).toBeNull();
  });

  it("sets a slug, returning why the Mac refused it", async () => {
    const { api, dispatched, actions } = setup();
    expect(await actions.setPixieSlug("p1", "new")).toBeNull();
    expect(dispatched[0]).toMatchObject({ type: "pixie" });
    api.updatePixie.mockRejectedValueOnce(new ApiError(409, "taken"));
    expect(await actions.setPixieSlug("p1", "x")).toBe("taken");
    api.updatePixie.mockRejectedValueOnce(new ApiError(422, "bad slug"));
    expect(await actions.setPixieSlug("p1", "X")).toBe("bad slug");
    api.updatePixie.mockRejectedValueOnce(new Error("down"));
    expect(await actions.setPixieSlug("p1", "y")).toBeNull();
    expect(dispatched.at(-1)).toMatchObject({ type: "toast", toast: { text: "down" } });
  });

  it("lists notes and searches quietly", async () => {
    const { api, actions } = setup();
    api.pixieNotes.mockResolvedValueOnce(["a"]);
    expect(await actions.pixieNotes("p1")).toEqual(["a"]);
    api.pixieNotes.mockRejectedValueOnce(new Error("down"));
    expect(await actions.pixieNotes("p1")).toEqual([]);
    api.searchPixie.mockResolvedValueOnce([{ file: "MEMORY.md", line: "x" }]);
    expect(await actions.searchPixie("p1", "x")).toEqual([{ file: "MEMORY.md", line: "x" }]);
    api.searchPixie.mockRejectedValueOnce(new Error("down"));
    expect(await actions.searchPixie("p1", "x")).toEqual([]);
  });

  it("loads pixies with everything else", async () => {
    const { api, dispatched, actions } = setup();
    api.pixies.mockResolvedValueOnce([pixie()]);
    await actions.load();
    expect(dispatched).toContainEqual({ type: "pixies", pixies: [pixie()] });
  });
});

describe("each chat's pixies and subagents (B46)", () => {
  it("loads every chat's group and the agents of chats at work", async () => {
    const { api, dispatched, actions } = setup();
    const running = session({ state: "running" });
    api.sessions.mockImplementation((archived) =>
      Promise.resolve(archived ? [] : [running, session({ id: "s2" })]),
    );
    api.pixieGroups.mockResolvedValueOnce({ s1: [groupEntry()] });
    const agent = {
      id: "a1",
      name: "Explore",
      description: null,
      parent: null,
      status: "running" as const,
      activity: null,
      started_at: null,
      finished_at: null,
      steps: [],
    };
    api.session.mockResolvedValueOnce(detail({ ...running, agents: [agent] }));
    await actions.load();

    expect(dispatched).toContainEqual({ type: "pixieGroups", groups: { s1: [groupEntry()] } });
    expect(dispatched).toContainEqual({
      type: "tracking",
      id: "s1",
      tracking: { tasks: [], agents: [agent], background: detail().background },
    });
    expect(api.session.mock.calls).toEqual([["s1"]]);

    // Quietly: the chats still show without them.
    api.pixieGroups.mockRejectedValueOnce(new Error("down"));
    api.session.mockRejectedValueOnce(new Error("down"));
    const before = dispatched.length;
    await actions.load();
    expect(dispatched.slice(before).map((a) => a.type)).toEqual([
      "loaded",
      "claudeChats",
      "unseenArtifacts",
      "pixies",
      "teams",
      "reports",
    ]);
  });

  it("sends a pixie away and takes the group the Mac returns", async () => {
    const { api, dispatched, actions } = setup();
    api.sendAway.mockResolvedValueOnce([groupEntry({ pixie_id: "p2" })]);
    expect(await actions.sendAway("s1", { pixie_id: "p1" })).toBe(true);
    expect(api.sendAway).toHaveBeenCalledWith("s1", { pixie_id: "p1" });
    expect(dispatched).toEqual([
      { type: "pixieGroup", id: "s1", group: [groupEntry({ pixie_id: "p2" })] },
    ]);
    api.sendAway.mockRejectedValueOnce(new Error("down"));
    expect(await actions.sendAway("s1", { team_id: "t1" })).toBe(false);
    expect(dispatched.at(-1)).toMatchObject({ type: "toast", toast: { text: "down" } });
  });

  it("reads a pixie's calls and a subagent's transcript, null when they cannot be read", async () => {
    const { api, actions } = setup();
    api.pixieCalls.mockResolvedValueOnce([callWork()]);
    expect(await actions.pixieCalls("s1", "p1")).toEqual([callWork()]);
    expect(await actions.agentTranscript("s1", "a1")).toMatchObject({ tool_use_id: "a1" });
    api.pixieCalls.mockRejectedValueOnce(new Error("down"));
    api.agentTranscript.mockRejectedValueOnce(new ApiError(404, "gone"));
    expect(await actions.pixieCalls("s1", "p1")).toBeNull();
    expect(await actions.agentTranscript("s1", "a1")).toBeNull();
  });

  it("returns why a message calling a team member was refused, without a toast", async () => {
    const { api, dispatched, actions } = setup();
    const why = "Bugs is in @qa; call the team or a solo copy";
    api.sendMessage.mockRejectedValueOnce(new ApiError(422, why, "pixie_in_team"));
    expect(await actions.send("s1", "@bugs look", [])).toEqual({ refused: why });
    expect(dispatched).toEqual([]);
  });
});

describe("stopping a background task (B59)", () => {
  it("sends the stop, and tells a finished task and a closed run apart", async () => {
    const { api, dispatched, actions } = setup();
    expect(await actions.stopTask("s1", "a1")).toBe("sent");
    expect(api.stopTask).toHaveBeenCalledWith("s1", "a1");

    // A task that already finished: its row is fetched again.
    api.stopTask.mockRejectedValueOnce(new ApiError(404, "session 's1' has no running task 'a1'"));
    expect(await actions.stopTask("s1", "a1")).toBe("gone");
    expect(api.session).toHaveBeenCalledWith("s1");

    api.stopTask.mockRejectedValueOnce(new ApiError(409, "session 's1' has no agent running"));
    expect(await actions.stopTask("s1", "a1")).toBe("closed");
    expect(dispatched.filter((a) => a.type === "toast")).toEqual([]);

    api.stopTask.mockRejectedValueOnce(new Error("down"));
    expect(await actions.stopTask("s1", "a1")).toBe("failed");
    expect(dispatched.at(-1)).toMatchObject({ type: "toast", toast: { text: "down" } });
  });
});

describe("artifact actions (B79)", () => {
  it("leaves the badge as it was when the count cannot be read", async () => {
    const { api, dispatched, actions } = setup();
    api.artifactsUnseen.mockRejectedValueOnce(new Error("offline"));
    await actions.reloadArtifacts();
    expect(dispatched).toEqual([]);
  });

  it("reads each version once, and again after a failure", async () => {
    const { api, actions } = setup();
    api.artifactVersion.mockRejectedValueOnce(new Error("offline"));
    expect(await actions.artifactVersion("a1", 2)).toBeNull();
    expect(await actions.artifactVersion("a1", 2)).toEqual(
      artifactContent({ artifact_id: "a1", version: 2 }),
    );
    await actions.artifactVersion("a1", 2);
    expect(api.artifactVersion).toHaveBeenCalledTimes(2);
  });

  it("marks one seen quietly, keeping what it was on failure", async () => {
    const { api, dispatched, actions } = setup();
    api.markArtifactSeen.mockRejectedValueOnce(new Error("offline"));
    await actions.markArtifactSeen("a1");
    expect(dispatched).toEqual([]);
    await actions.markArtifactSeen("a1");
    expect(dispatched).toEqual([{ type: "artifact", artifact: artifact({ seen: true }) }]);
  });

  it("reports a refused delete and keeps the artifact", async () => {
    const { api, dispatched, actions } = setup();
    api.deleteArtifact.mockRejectedValueOnce(new ApiError(404, "unknown artifact"));
    expect(await actions.deleteArtifact("a1")).toBe(false);
    expect(dispatched).toEqual([
      { type: "toast", toast: { id: 1, text: "unknown artifact", tone: "error" } },
    ]);
  });

  it("saves a user's edit of a document and reads the artifact again (B88)", async () => {
    const { api, dispatched, actions } = setup();
    const saved = { version: 4, title: "Plan", size: 6, created_at: "x", author: "user" as const };
    api.saveArtifactVersion.mockResolvedValueOnce(saved);
    api.artifact.mockResolvedValueOnce(artifactDetail({ latest_version: 4 }));
    expect(await actions.saveArtifactDocument("a1", "# Plan", 3)).toEqual(saved);
    expect(api.saveArtifactVersion).toHaveBeenCalledWith("a1", {
      content: "# Plan",
      base_version: 3,
    });
    expect(dispatched).toEqual([
      { type: "artifact", artifact: artifactDetail({ latest_version: 4 }) },
    ]);
  });

  it("passes a refused save on to the page, with no toast", async () => {
    const { api, dispatched, actions } = setup();
    const stale = new ApiError(409, "changed");
    api.saveArtifactVersion.mockRejectedValueOnce(stale);
    await expect(actions.saveArtifactDocument("a1", "x", 1)).rejects.toBe(stale);
    expect(dispatched).toEqual([]);
    expect(api.artifact).not.toHaveBeenCalled();
  });

  it("reads what a page stored quietly, null when it cannot (B88)", async () => {
    const { api, dispatched, actions } = setup();
    expect(await actions.artifactStorage("a1")).toEqual({ items: {}, size: 0 });
    api.artifactStorage.mockRejectedValueOnce(new Error("offline"));
    expect(await actions.artifactStorage("a1")).toBeNull();
    expect(dispatched).toEqual([]);
  });

  it("writes and clears a page's data, leaving refusals to the caller", async () => {
    const { api, dispatched, actions } = setup();
    api.writeArtifactStorage.mockResolvedValueOnce({ size: 7 });
    expect(await actions.writeArtifactStorage("a1", { set: { k: "v" }, remove: [] })).toEqual({
      size: 7,
    });
    expect(api.writeArtifactStorage).toHaveBeenCalledWith("a1", { set: { k: "v" }, remove: [] });
    await actions.clearArtifactStorage("a1");
    expect(api.clearArtifactStorage).toHaveBeenCalledWith("a1");
    const full = new ApiError(413, "Over 2 MiB");
    api.writeArtifactStorage.mockRejectedValueOnce(full);
    await expect(actions.writeArtifactStorage("a1", { set: {}, remove: [] })).rejects.toBe(full);
    expect(dispatched).toEqual([]);
  });

  it("tells those listening of storage changes, and stops when they leave", () => {
    const { dispatched, actions } = setup();
    const heard: unknown[] = [];
    const leave = actions.onArtifactStorage((change) => heard.push(change));
    const change = { artifact_id: "a1", set: { k: "v" }, remove: [], clear: false };
    actions.receive(event({ id: null, type: "artifact.storage", payload: change }));
    actions.receive(event({ id: null, type: "artifact.seen", payload: { artifact_id: "a1" } }));
    leave();
    actions.receive(event({ id: null, type: "artifact.storage", payload: change }));
    expect(heard).toEqual([change]);
    expect(dispatched.map((a) => a.type)).toEqual(["event", "event", "event"]);
  });

  it("reads a storage change's fields plainly, and skips one naming no artifact", () => {
    const { actions } = setup();
    const heard: unknown[] = [];
    actions.onArtifactStorage((change) => heard.push(change));
    actions.receive(event({ id: null, type: "artifact.storage", payload: { set: { a: "1" } } }));
    actions.receive(
      event({
        id: null,
        type: "artifact.storage",
        payload: { artifact_id: "a1", set: { a: "1", b: 2 }, remove: ["c", 3], clear: "yes" },
      }),
    );
    actions.receive(
      event({ id: null, type: "artifact.storage", payload: { artifact_id: "a2", clear: true } }),
    );
    expect(heard).toEqual([
      { artifact_id: "a1", set: { a: "1" }, remove: ["c"], clear: false },
      { artifact_id: "a2", set: {}, remove: [], clear: true },
    ]);
  });

  it("reads usage for a page: the limits, today and this week, fresh for a minute", async () => {
    vi.useFakeTimers({ now: new Date(2026, 9, 17, 15, 0), toFake: ["Date"] });
    const { api, actions } = setup();
    api.usagePeriod.mockImplementation((unit) =>
      Promise.resolve(
        usagePeriod({
          unit,
          sessions: unit === "day" ? 3 : 20,
          tokens: { ...usagePeriod().tokens, total: unit === "day" ? 900 : 7000 },
        }),
      ),
    );
    const expected = {
      limits: { five_hour: { utilization: 0.3, resets_at: null }, seven_day: null },
      today: { tokens: 900, sessions: 3 },
      week: { tokens: 7000, sessions: 20 },
    };
    expect(await actions.pageUsage()).toEqual(expected);
    expect(api.usagePeriod).toHaveBeenCalledWith("day", "2026-10-17");
    expect(api.usagePeriod).toHaveBeenCalledWith("week", "2026-10-17");
    await actions.pageUsage();
    expect(api.usageLimits).toHaveBeenCalledTimes(1);
    vi.setSystemTime(new Date(2026, 9, 17, 15, 1, 1));
    await actions.pageUsage();
    expect(api.usageLimits).toHaveBeenCalledTimes(2);
    await actions.pageUsage(true);
    expect(api.usageLimits).toHaveBeenCalledTimes(3);
    vi.useRealTimers();
  });

  it("reads usage again after a failure", async () => {
    const { api, actions } = setup();
    api.usageLimits.mockRejectedValueOnce(new Error("offline"));
    await expect(actions.pageUsage()).rejects.toThrow("offline");
    await actions.pageUsage();
    expect(api.usageLimits).toHaveBeenCalledTimes(2);
  });

  it("keeps a newer read when an older one fails after it", async () => {
    const { api, actions } = setup();
    let fail: (error: Error) => void = () => undefined;
    api.usageLimits.mockImplementationOnce(
      () =>
        new Promise((_, reject) => {
          fail = reject;
        }),
    );
    const old = actions.pageUsage();
    const fresh = actions.pageUsage(true);
    fail(new Error("offline"));
    await expect(old).rejects.toThrow("offline");
    await fresh;
    await actions.pageUsage();
    expect(api.usageLimits).toHaveBeenCalledTimes(2);
  });

  it("reads today's asks quietly, null when it cannot", async () => {
    const { api, dispatched, actions } = setup();
    expect(await actions.askStatus("a1")).toEqual({
      used: 0,
      limit: 20,
      remaining: 20,
      resets_at: null,
      enabled: true,
    });
    expect(api.askStatus).toHaveBeenCalledWith("a1");
    api.askStatus.mockRejectedValueOnce(new Error("offline"));
    expect(await actions.askStatus("a1")).toBeNull();
    expect(dispatched).toEqual([]);
  });

  it("asks Claude for a page, leaving refusals to the caller", async () => {
    const { api, dispatched, actions } = setup();
    expect(await actions.askArtifact("a1", { prompt: "Hi" })).toEqual({
      text: "Hello",
      remaining: 19,
    });
    expect(api.askArtifact).toHaveBeenCalledWith("a1", { prompt: "Hi" });
    api.askArtifact.mockRejectedValueOnce(new ApiError(429, "used"));
    await expect(actions.askArtifact("a1", { prompt: "Hi" })).rejects.toThrow("used");
    expect(dispatched).toEqual([]);
  });

  it("tells those listening of every event, until they leave", () => {
    const { actions } = setup();
    const heard: string[] = [];
    const leave = actions.onEvent((received) => heard.push(received.type));
    actions.receive(event({ id: null, type: "artifact.ask", payload: {} }));
    leave();
    actions.receive(event({ id: null, type: "usage.updated", payload: {} }));
    expect(heard).toEqual(["artifact.ask"]);
  });

  it("looks an artifact up once while a lookup runs", async () => {
    const { api, actions } = setup();
    await Promise.all([actions.loadArtifact("a1"), actions.loadArtifact("a1")]);
    expect(api.artifact).toHaveBeenCalledTimes(1);
    await actions.loadArtifact("a1");
    expect(api.artifact).toHaveBeenCalledTimes(2);
  });
});

describe("usage actions", () => {
  it("shows a period and loads it, toasting a failure (B84)", async () => {
    const { api, dispatched, actions } = setup();
    actions.viewUsage("week", "2026-10-14");
    await actions.loadUsage("week", "2026-10-14");
    expect(api.usagePeriod).toHaveBeenCalledWith("week", "2026-10-14");
    expect(dispatched).toEqual([
      { type: "usageView", unit: "week", date: "2026-10-14" },
      { type: "usagePeriod", period: usagePeriod() },
    ]);
    api.usagePeriod.mockRejectedValueOnce(new ApiError(422, "bad date"));
    await actions.loadUsage("week", "x");
    expect(dispatched.at(-1)).toEqual({
      type: "toast",
      toast: { id: 1, text: "bad date", tone: "error" },
    });
  });
});

describe("engines (B102)", () => {
  it("loads the engines, the agent defaults and every engine's models", async () => {
    const { api, dispatched, actions } = setup();
    api.providers.mockResolvedValueOnce({ providers: [claudeProvider(), codexProvider()] });
    const codex = modelList({ models: [], default_model: "gpt-5.5" });
    api.models.mockImplementation((provider) =>
      Promise.resolve(provider === "codex" ? codex : modelList()),
    );

    await actions.loadChoices();

    expect(api.models).toHaveBeenCalledWith();
    expect(api.models).toHaveBeenCalledWith("codex");
    expect(dispatched).toEqual([
      { type: "providers", providers: [claudeProvider(), codexProvider()] },
      { type: "modelList", provider: "claude", list: modelList() },
      { type: "agentDefaults", defaults: agentDefaults() },
      { type: "modelList", provider: "codex", list: codex },
    ]);
  });

  it("keeps what it had of a part the Mac cannot give", async () => {
    const { api, dispatched, actions } = setup();
    api.providers.mockRejectedValueOnce(new Error("old daemon"));
    api.models.mockRejectedValueOnce(new Error("down"));
    api.agentDefaults.mockRejectedValueOnce(new Error("down"));
    await actions.loadChoices();
    expect(dispatched).toEqual([]);

    api.providers.mockResolvedValueOnce({ providers: [claudeProvider(), codexProvider()] });
    api.models.mockRejectedValueOnce(new Error("codex down"));
    await actions.loadProviders(true);
    expect(api.providers).toHaveBeenLastCalledWith(true);
    expect(dispatched.map((a) => a.type)).toEqual(["providers"]);

    api.providers.mockRejectedValueOnce(new Error("down"));
    await actions.loadProviders();
    expect(dispatched).toHaveLength(1);
  });

  it("loads Codex's usage windows quietly", async () => {
    const { api, dispatched, actions } = setup();
    await actions.loadEngineLimits();
    expect(api.engineLimits).toHaveBeenCalledWith("codex");
    expect(dispatched).toEqual([
      { type: "engineLimits", provider: "codex", limits: engineLimits() },
    ]);
    api.engineLimits.mockRejectedValueOnce(new Error("no codex"));
    await actions.loadEngineLimits();
    expect(dispatched).toHaveLength(1);
  });

  it("refreshes another engine's usage, saying when it was refreshed moments ago", async () => {
    const { api, dispatched, actions } = setup();
    await actions.refreshUsage("codex");
    expect(api.refreshEngineUsage).toHaveBeenCalledWith("codex");
    expect(api.refreshUsage).not.toHaveBeenCalled();
    expect(dispatched).toEqual([
      { type: "engineLimits", provider: "codex", limits: engineLimits() },
    ]);
    api.refreshEngineUsage.mockRejectedValueOnce(new ApiError(429, "too soon"));
    await actions.refreshUsage("codex");
    expect(dispatched.at(-1)).toMatchObject({
      type: "toast",
      toast: { text: "Usage was refreshed moments ago", tone: "info" },
    });
    await actions.refreshUsage("claude");
    expect(api.refreshUsage).toHaveBeenCalledTimes(1);
  });

  it("remembers the usage bar's engines on this device", () => {
    localStorage.removeItem(USAGE_BAR_HIDDEN_KEY);
    const { dispatched, actions } = setup();
    actions.setUsageBarEngine("codex", false);
    actions.setUsageBarEngine("claude", false);
    actions.setUsageBarEngine("claude", true);
    expect(loadUsageBarHidden(() => localStorage)).toEqual(["codex"]);
    expect(dispatched).toEqual([
      { type: "usageBarEngine", provider: "codex", shown: false },
      { type: "usageBarEngine", provider: "claude", shown: false },
      { type: "usageBarEngine", provider: "claude", shown: true },
    ]);
    localStorage.removeItem(USAGE_BAR_HIDDEN_KEY);
  });

  it("asks for the engines again when Codex's account changes", async () => {
    const { api, actions } = setup();
    actions.receive(
      event({ type: "account.codex", session_id: null, payload: { ...codexAccount() } }),
    );
    await vi.waitFor(() => {
      expect(api.providers).toHaveBeenCalledWith(false);
    });
  });
});

describe("merging (B102 item 30)", () => {
  it("keeps the branch unless asked to delete it", async () => {
    const { api, actions } = setup();
    expect(await actions.merge(mergeApproval(), 7)).toBe(true);
    expect(api.merge).toHaveBeenLastCalledWith("s1", { method: "squash", delete_branch: false });
    expect(await actions.merge(mergeApproval(), 7, true)).toBe(true);
    expect(api.merge).toHaveBeenLastCalledWith("s1", { method: "squash", delete_branch: true });
  });
});
