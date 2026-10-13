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

  it("loads pixies with everything else", async () => {
    const { api, dispatched, actions } = setup();
    api.pixies.mockResolvedValueOnce([pixie()]);
    await actions.load();
    expect(dispatched).toContainEqual({ type: "pixies", pixies: [pixie()] });
  });
});
