import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client.ts";
import { fakeApi } from "../test/fakeApi.ts";
import { pixie, session, team } from "../test/fixtures.ts";
import { FOLDED_TEAMS_KEY, loadFoldedTeams } from "./devicePrefs.ts";
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
    expect(dispatched.map((a) => a.type)).toEqual(["loaded", "claudeChats", "teams", "reports"]);
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
