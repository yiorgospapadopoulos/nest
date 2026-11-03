// Ported from NestKitTests' RunControlTests (B108): what the header's Run control shows.
import { describe, expect, it } from "vitest";
import type { RunStatus } from "../../api/types.ts";
import { runControl, runPorts } from "./runState.ts";

const status = (over: Partial<RunStatus> = {}): RunStatus => ({
  available: true,
  command: "npm run dev",
  folder: "/w/cv",
  block: { start: 41020, end: 41029 },
  state: "stopped",
  listening: [],
  exit_code: null,
  started_at: null,
  ...over,
});

describe("the Run control", () => {
  it("shows nothing without a run command", () => {
    expect(runControl(null)).toBeNull();
    expect(runControl(status({ available: false }))).toBeNull();
    expect(runControl(status({ command: null }))).toBeNull();
  });

  it("offers Run when stopped or after a clean exit, and says a failed exit's code", () => {
    const run = { kind: "run", help: "Run npm run dev" };
    expect(runControl(status())).toEqual(run);
    expect(runControl(status({ state: "exited", exit_code: 0 }))).toEqual(run);
    expect(runControl(status({ state: "exited", exit_code: 1 }))).toEqual({
      kind: "exited",
      label: "Exited 1",
      help: "npm run dev exited with code 1. Click to run again",
    });
  });

  it("reads as starting until a port listens", () => {
    const starting = { kind: "starting", help: "Starting npm run dev. Click to stop" };
    expect(runControl(status({ state: "starting" }))).toEqual(starting);
    expect(runControl(status({ state: "running" }))).toEqual(starting);
  });

  it("shows up to three ports, else two and the rest, and one in a narrow pane", () => {
    const four = status({ state: "running", listening: [41020, 41021, 41022, 41023] });
    const wide = runControl(four);
    expect(wide).toMatchObject({ kind: "running", more: 2, moreHelp: "Also 41022, 41023" });
    if (wide?.kind === "running") expect(wide.ports.map((p) => p.port)).toEqual([41020, 41021]);
    const narrow = runControl(four, true);
    expect(narrow).toMatchObject({ more: 3, moreHelp: "Also 41021, 41022, 41023" });
    const three = runControl(status({ state: "running", listening: [41020, 41021, 41022] }));
    expect(three).toMatchObject({ more: 0, moreHelp: null });
  });

  it("says when a port is outside the folder's block, and never opens another machine's", () => {
    const ports = runPorts(status({ state: "running", listening: [5173, 41020] }));
    expect(ports[0]).toEqual({
      port: 5173,
      live: true,
      url: "http://localhost:5173",
      help: "Outside this folder's ports 41020 to 41029",
    });
    expect(ports[1]?.help).toBe("Open localhost:41020");
    const remote = runPorts(status({ state: "running", listening: [41020] }), "Mac mini");
    expect(remote[0]).toMatchObject({ url: null, help: "Runs on Mac mini" });
  });
});
