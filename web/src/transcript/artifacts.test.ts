import { describe, expect, it } from "vitest";
import type { JsonObject } from "../api/types.ts";
import { event } from "../test/fixtures.ts";
import { buildTranscript } from "./build.ts";

const BIG = "x".repeat(5000);

const message = (id: number, blocks: JsonObject[], parent: string | null = null) =>
  event({ id, type: "session.message", payload: { parent_tool_use_id: parent, blocks } });

const saved = (id: number, payload: JsonObject) => event({ id, type: "session.artifact", payload });

const create = (id: string, title = "Options") => ({
  type: "tool_use",
  id,
  name: "mcp__nest__create_artifact",
  input: { title, kind: "markdown", content: BIG },
});

const result = (id: string, content: string, failed = false) => ({
  type: "tool_result",
  tool_use_id: id,
  content,
  ...(failed ? { is_error: true } : {}),
});

describe("artifacts in the transcript (B79)", () => {
  it("shows a save as its card, without the call's row", () => {
    const items = buildTranscript(
      [
        message(1, [create("t1")]),
        saved(2, {
          artifact_id: "a1",
          version: 1,
          title: "Options",
          kind: "markdown",
          action: "created",
        }),
        message(3, [result("t1", "Saved artifact a1 (version 1): Options. The user opens it...")]),
        saved(4, {
          artifact_id: "a1",
          version: 2,
          title: "Options v2",
          kind: "html",
          action: "updated",
        }),
      ],
      {},
      null,
    );
    expect(items).toEqual([
      {
        kind: "artifact",
        key: "2",
        artifactId: "a1",
        version: 1,
        title: "Options",
        artifactKind: "markdown",
        action: "created",
      },
      {
        kind: "artifact",
        key: "4",
        artifactId: "a1",
        version: 2,
        title: "Options v2",
        artifactKind: "html",
        action: "updated",
      },
    ]);
  });

  it("keeps a failed save as a tool row, and a running one, by name and title only", () => {
    const update = {
      type: "tool_use",
      id: "t2",
      name: "mcp__nest__update_artifact",
      input: { artifact_id: "zz", content: BIG },
    };
    const items = buildTranscript(
      [
        message(1, [create("t1", "Plan"), update, create("t3", "Later")]),
        message(2, [result("t1", "kind: Input should be 'markdown' or 'html'.", true)]),
        message(3, [result("t2", "unknown artifact 'zz'", true)]),
      ],
      {},
      null,
      new Set(["t3"]),
    );
    expect(items).toHaveLength(1);
    const group = items[0];
    expect(group?.kind).toBe("tools");
    const rows = group?.kind === "tools" ? group.items : [];
    expect(
      rows.map((row) => (row.kind === "tool" ? [row.name, row.arg, row.result] : null)),
    ).toEqual([
      ["Save artifact", "Plan", "failed"],
      ["Update artifact", "", "failed"],
      ["Save artifact", "Later", null],
    ]);
    expect(JSON.stringify(items)).not.toContain(BIG);
  });

  it("names a subagent's save without its content", () => {
    const items = buildTranscript(
      [
        message(1, [
          { type: "tool_use", id: "ag", name: "Agent", input: { description: "Write it" } },
        ]),
        message(2, [create("t1", "Notes")], "ag"),
      ],
      {},
      null,
    );
    const call = items[0];
    expect(call?.kind === "tool" ? call.steps : null).toEqual([
      { kind: "call", key: "2.0", text: "Save artifact Notes" },
    ]);
  });

  it.each(["slides", "document", "design", "design_system"])(
    "names a %s card's kind (B88)",
    (kind) => {
      const items = buildTranscript(
        [saved(1, { artifact_id: "a1", version: 1, title: "T", kind, action: "created" })],
        {},
        null,
      );
      expect(items[0]).toMatchObject({ kind: "artifact", artifactKind: kind });
    },
  );

  it("leaves out a malformed card and reads unknown fields plainly", () => {
    const items = buildTranscript(
      [
        saved(1, { version: 1 }),
        saved(2, { artifact_id: "a1" }),
        saved(3, { artifact_id: "a1", version: 3, kind: "pdf", action: "renamed" }),
      ],
      {},
      null,
    );
    expect(items).toEqual([
      {
        kind: "artifact",
        key: "3",
        artifactId: "a1",
        version: 3,
        title: "Artifact",
        artifactKind: "markdown",
        action: "created",
      },
    ]);
  });
});
