import { describe, expect, it } from "vitest";
import type { JsonValue } from "../api/types.ts";
import { event, runStatus } from "../test/fixtures.ts";
import { reduce } from "./reducer.ts";
import { lastLines, OUTPUT_LINES } from "./runs.ts";
import { initialState, type State } from "./state.ts";

const running = runStatus({
  available: true,
  command: "npm run dev",
  state: "running",
  listening: [41020],
  started_at: "2026-10-26T22:41:07Z",
});

/** Two chats in one folder and one elsewhere, each with its run known. */
function known(): State {
  let state = reduce(initialState, { type: "run", id: "s1", status: runStatus() });
  state = reduce(state, { type: "run", id: "s2", status: runStatus() });
  return reduce(state, { type: "run", id: "s3", status: runStatus({ folder: "/w/other" }) });
}

const changed = (payload: Record<string, JsonValue>) =>
  event({ type: "run.changed", id: null, session_id: null, payload });

const output = (folder: string, text: string) =>
  event({ type: "run.output", id: null, session_id: null, payload: { folder, text } });

describe("runs", () => {
  it("gives a chat's fetched run to the other chats in its folder", () => {
    const state = reduce(known(), { type: "run", id: "s2", status: running });
    expect(state.runs.s1).toEqual(running);
    expect(state.runs.s2).toEqual(running);
    expect(state.runs.s3?.state).toBe("stopped");
  });

  it("matches run.changed to chats by folder", () => {
    const state = reduce(known(), {
      type: "event",
      event: changed({ folder: "/w/s1", repo: "todo-ui", status: { ...running } }),
    });
    expect(state.runs.s1).toEqual(running);
    expect(state.runs.s2).toEqual(running);
    expect(state.runs.s3?.state).toBe("stopped");
  });

  it("adds no chat for a folder no chat showed", () => {
    const state = reduce(known(), {
      type: "event",
      event: changed({ folder: "/w/new", status: { ...running, folder: "/w/new" } }),
    });
    expect(Object.keys(state.runs)).toEqual(["s1", "s2", "s3"]);
  });

  it("never matches a status without a folder to chats without one", () => {
    let state = reduce(initialState, {
      type: "run",
      id: "s1",
      status: runStatus({ folder: null }),
    });
    state = reduce(state, {
      type: "run",
      id: "s2",
      status: runStatus({ folder: null, state: "exited" }),
    });
    expect(state.runs.s1?.state).toBe("stopped");
  });

  it("ignores a run.changed without a status", () => {
    const before = known();
    expect(reduce(before, { type: "event", event: changed({ folder: "/w/s1" }) }).runs).toEqual(
      before.runs,
    );
  });

  it("keeps output only for an open folder, adding each chunk", () => {
    let state = reduce(initialState, {
      type: "runOutput",
      folder: "/w/s1",
      text: "$ npm run dev\n",
    });
    state = reduce(state, { type: "event", event: output("/w/s1", "ready in ") });
    state = reduce(state, { type: "event", event: output("/w/s1", "412 ms\n") });
    state = reduce(state, { type: "event", event: output("/w/other", "elsewhere") });
    state = reduce(state, {
      type: "event",
      event: event({ type: "run.output", id: null, payload: { text: "no folder" } }),
    });
    state = reduce(state, {
      type: "event",
      event: event({ type: "run.output", id: null, payload: { folder: "/w/s1" } }),
    });
    expect(state.runOutput).toEqual({ "/w/s1": "$ npm run dev\nready in 412 ms\n" });

    state = reduce(state, { type: "runOutput", folder: "/w/s1", text: null });
    state = reduce(state, { type: "event", event: output("/w/s1", "later") });
    expect(state.runOutput).toEqual({});
  });

  it("keeps the last lines the daemon keeps", () => {
    const lines = Array.from({ length: OUTPUT_LINES + 5 }, (_, i) => `line ${String(i)}`);
    const kept = lastLines(`${lines.join("\n")}\npart`).split("\n");
    expect(kept).toHaveLength(OUTPUT_LINES + 1);
    expect(kept[0]).toBe("line 5");
    expect(kept.at(-1)).toBe("part");
    expect(lastLines("a\nb\n")).toBe("a\nb\n");
  });
});
