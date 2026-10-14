import { describe, expect, it } from "vitest";
import { commandList } from "../../test/fixtures.ts";
import { matchCommands, replaceTrigger, soulLine, triggerAt } from "./suggest.ts";

describe("triggerAt", () => {
  it("finds a slash command only at the very start", () => {
    expect(triggerAt("/", 1)).toEqual({ kind: "command", start: 0, end: 1, query: "" });
    expect(triggerAt("/com", 4)).toEqual({ kind: "command", start: 0, end: 4, query: "com" });
    // The caret inside the token: the whole token is replaced.
    expect(triggerAt("/compact now", 3)).toEqual({
      kind: "command",
      start: 0,
      end: 8,
      query: "co",
    });
    expect(triggerAt("/compact now", 10)).toBeNull();
    expect(triggerAt(" /com", 5)).toBeNull();
    expect(triggerAt("hi /com", 7)).toBeNull();
  });

  it("finds an @ mention at the start of a word", () => {
    expect(triggerAt("@", 1)).toEqual({ kind: "file", start: 0, end: 1, query: "" });
    expect(triggerAt("Look at @src/a", 14)).toEqual({
      kind: "file",
      start: 8,
      end: 14,
      query: "src/a",
    });
    expect(triggerAt("see\n@ap more", 7)).toEqual({ kind: "file", start: 4, end: 7, query: "ap" });
    expect(triggerAt("me@example.com", 14)).toBeNull();
    expect(triggerAt("@a b", 4)).toBeNull();
    expect(triggerAt("plain text", 5)).toBeNull();
  });
});

describe("replaceTrigger", () => {
  it("puts the choice in place of the token, followed by one space", () => {
    expect(
      replaceTrigger("/co", { kind: "command", start: 0, end: 3, query: "co" }, "/compact"),
    ).toEqual({
      text: "/compact ",
      caret: 9,
    });
    expect(
      replaceTrigger("/co focus", { kind: "command", start: 0, end: 3, query: "co" }, "/compact"),
    ).toEqual({ text: "/compact focus", caret: 9 });
    expect(
      replaceTrigger("see @ap now", { kind: "file", start: 4, end: 7, query: "ap" }, "@src/app.py"),
    ).toEqual({ text: "see @src/app.py now", caret: 16 });
  });
});

describe("matchCommands", () => {
  const { commands } = commandList();
  const names = (query: string) => matchCommands(commands, query).map((c) => c.name);

  it("lists prefix matches first, then matches inside the name, ignoring case", () => {
    expect(names("")).toEqual(["clear", "compact", "review", "security-review"]);
    expect(names("RE")).toEqual(["review", "security-review"]);
    expect(names("c")).toEqual(["clear", "compact", "security-review"]);
    expect(names("zzz")).toEqual([]);
  });
});

describe("soulLine", () => {
  it("is the first line with text, without heading marks", () => {
    expect(soulLine("\n  \n## You review code\nMore")).toBe("You review code");
    expect(soulLine("Plain first line\n")).toBe("Plain first line");
    expect(soulLine("\n \n")).toBe("");
    expect(soulLine("")).toBe("");
  });
});
