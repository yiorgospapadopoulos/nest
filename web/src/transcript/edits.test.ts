import { describe, expect, it } from "vitest";
import { editDiff, lineDiff } from "./edits.ts";

const shape = (lines: { kind: string; text: string }[]) =>
  lines.map(
    ({ kind, text }) => `${{ add: "+", del: "-", ctx: " ", gap: "~" }[kind] ?? "?"}${text}`,
  );

describe("lineDiff", () => {
  it("keeps the shared lines around a change as context", () => {
    const lines = lineDiff("a\nb\nc\nd", "a\nB\nc\nd");

    expect(shape(lines)).toEqual([" a", "-b", "+B", " c", " d"]);
  });

  it("finds lines kept in the middle of a change", () => {
    const lines = lineDiff("one\nkeep\ntwo", "uno\nkeep\ndos\ntres");

    expect(shape(lines)).toEqual(["-one", "+uno", " keep", "-two", "+dos", "+tres"]);
  });

  it("reads a final newline as the end of the last line, not an empty one", () => {
    expect(shape(lineDiff("a\n", "a\nb\n"))).toEqual([" a", "+b"]);
  });

  it("handles text that is all new or all gone", () => {
    expect(shape(lineDiff("", "x\ny"))).toEqual(["+x", "+y"]);
    expect(shape(lineDiff("x", ""))).toEqual(["-x"]);
    expect(lineDiff("", "")).toEqual([]);
  });

  it("removes then adds every changed line when the change is too large to match", () => {
    const before = Array.from({ length: 700 }, (_, i) => `old ${String(i)}`).join("\n");
    const after = Array.from({ length: 700 }, (_, i) => `new ${String(i)}`).join("\n");

    const lines = lineDiff(`top\n${before}`, `top\n${after}`);

    expect(lines).toHaveLength(1401);
    expect(lines[0]).toEqual({ kind: "ctx", text: "top" });
    expect(lines.slice(1, 701).every((line) => line.kind === "del")).toBe(true);
    expect(lines.slice(701).every((line) => line.kind === "add")).toBe(true);
  });
});

describe("editDiff", () => {
  it("diffs an Edit's old and new text, with counts", () => {
    const diff = editDiff("Edit", {
      file_path: "/w/a.ts",
      old_string: "const a = 1;\nconst b = 2;",
      new_string: "const a = 1;\nconst b = 3;\nconst c = 4;",
    });

    expect(diff).toEqual({
      added: 2,
      removed: 1,
      lines: [
        { kind: "ctx", text: "const a = 1;" },
        { kind: "del", text: "const b = 2;" },
        { kind: "add", text: "const b = 3;" },
        { kind: "add", text: "const c = 4;" },
      ],
    });
  });

  it("joins a MultiEdit's edits with a gap between them, skipping malformed ones", () => {
    const diff = editDiff("MultiEdit", {
      file_path: "/w/a.ts",
      edits: [
        { old_string: "a", new_string: "b" },
        "nonsense",
        { old_string: "x" },
        { old_string: "c", new_string: "d" },
      ],
    });

    expect(diff === null ? null : shape(diff.lines)).toEqual(["-a", "+b", "~", "-c", "+d"]);
    expect(diff?.added).toBe(2);
    expect(diff?.removed).toBe(2);
  });

  it("shows a Write's content as all added", () => {
    const diff = editDiff("Write", { file_path: "/w/new.md", content: "# Title\n\nBody\n" });

    expect(diff === null ? null : shape(diff.lines)).toEqual(["+# Title", "+", "+Body"]);
    expect(diff?.added).toBe(3);
    expect(diff?.removed).toBe(0);
  });

  it("shows a NotebookEdit's new cell source as added, and nothing for a deleted cell", () => {
    const diff = editDiff("NotebookEdit", {
      notebook_path: "/w/n.ipynb",
      new_source: "print(1)",
      edit_mode: "replace",
    });
    expect(diff === null ? null : shape(diff.lines)).toEqual(["+print(1)"]);

    expect(
      editDiff("NotebookEdit", {
        notebook_path: "/w/n.ipynb",
        new_source: "",
        edit_mode: "delete",
      }),
    ).toBeNull();
  });

  it("has no diff for other tools or inputs without the text", () => {
    expect(editDiff("Bash", { command: "ls" })).toBeNull();
    expect(editDiff("Edit", { file_path: "/w/a.ts" })).toBeNull();
    expect(editDiff("MultiEdit", { file_path: "/w/a.ts", edits: [] })).toBeNull();
    expect(editDiff("MultiEdit", { file_path: "/w/a.ts" })).toBeNull();
    expect(editDiff("Write", { file_path: "/w/a.ts" })).toBeNull();
    expect(editDiff("NotebookEdit", { notebook_path: "/w/n.ipynb" })).toBeNull();
  });

  it("has no diff for an edit that changes nothing visible", () => {
    expect(editDiff("Edit", { file_path: "/w/a.ts", old_string: "", new_string: "" })).toBeNull();
  });
});
