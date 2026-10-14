import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client.ts";
import { fakeApi } from "../test/fakeApi.ts";
import { pixie, session } from "../test/fixtures.ts";
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
  it("loads pixies, quietly on failure", async () => {
    const { api, dispatched, actions } = setup();
    api.pixies.mockResolvedValueOnce([pixie()]);
    await actions.loadPixies();
    expect(dispatched).toEqual([{ type: "pixies", pixies: [pixie()] }]);
    api.pixies.mockRejectedValueOnce(new Error("down"));
    await actions.loadPixies();
    expect(dispatched).toHaveLength(1);
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
    expect(dispatched.map((a) => a.type)).toEqual(["loaded", "claudeChats"]);
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
