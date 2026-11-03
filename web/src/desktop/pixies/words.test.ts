import { describe, expect, it } from "vitest";
import { addingFact, factCount, facts, removingLine, shortName, skillMenu } from "./words.ts";

// Ported from NestKitTests' PixiePresentationTests and PixieTeamsTests.

describe("memory facts", () => {
  it("are read, added and removed by their line", () => {
    const text = "# Memory\n- 2026-10-10: Small pull requests.\n- Undated fact\nplain line\n";
    expect(facts(text)).toEqual([
      { line: 1, date: "2026-10-10", text: "Small pull requests." },
      { line: 2, date: "", text: "Undated fact" },
    ]);
    expect(factCount(text)).toBe("2 facts");
    expect(factCount("- one")).toBe("1 fact");
    expect(addingFact("New", "", "2026-10-13")).toBe("- 2026-10-13: New\n");
    expect(addingFact("New", "# Memory", "2026-10-13")).toBe("# Memory\n- 2026-10-13: New\n");
    expect(addingFact("New", "# M\n", "2026-10-13")).toBe("# M\n- 2026-10-13: New\n");
    expect(removingLine(1, text)).toBe("# Memory\n- Undated fact\nplain line\n");
    expect(removingLine(40, text)).toBe(text);
  });
});

describe("the skills to add", () => {
  const choices = [
    { name: "code-review:review", description: "Reviews", plugin: "code-review" },
    { name: "notes", description: null, plugin: null },
    { name: "pdf:fill", description: null, plugin: "pdf" },
    { name: "code-review:diff", description: null, plugin: "code-review" },
    { name: "release-notes", description: null, plugin: null },
  ];

  it("are the ones not chosen, standalone first, then grouped by plugin", () => {
    const menu = skillMenu(choices, ["notes", "pdf:fill"]);
    expect(menu.standalone.map((s) => s.name)).toEqual(["release-notes"]);
    expect(menu.groups.map((g) => g.plugin)).toEqual(["code-review"]);
    expect(menu.groups[0]?.skills.map(shortName)).toEqual(["diff", "review"]);
    expect(menu.empty).toBeNull();
    expect(
      skillMenu(
        choices,
        choices.map((c) => c.name),
      ).empty,
    ).toBe("Every installed skill is added");
    expect(skillMenu([], []).empty).toBe("No skills installed");
  });
});
