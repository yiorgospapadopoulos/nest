// @vitest-environment node
import { describe, expect, it } from "vitest";
import { pixie, team } from "../test/fixtures.ts";
import { leaderColor, mentionLabels, mentionParts } from "./mentions.ts";

describe("mentionParts", () => {
  const labels = new Map([
    ["tester", { name: "Tester", color: "#111111" }],
    ["qa", { name: "QA crew", color: "#222222" }],
  ]);

  it("shows whole @ tokens of a known pixie or team as its name, in colour", () => {
    expect(mentionParts("@tester check, then @qa.\n@nobody", labels)).toEqual([
      { text: "@Tester", color: "#111111" },
      { text: " check, then ", color: null },
      { text: "@QA crew", color: "#222222" },
      { text: ".\n@nobody", color: null },
    ]);
  });

  it("leaves tokens inside words or running on plain", () => {
    expect(mentionParts("me@tester @tester-2 @testers @tester_x @Tester", labels)).toEqual([
      { text: "me@tester @tester-2 @testers @tester_x @Tester", color: null },
    ]);
    expect(mentionParts("", labels)).toEqual([]);
  });
});

describe("mentionLabels", () => {
  it("names slugs and handles, colouring teams by their leader", () => {
    const pixies = {
      a: pixie({ id: "a", name: "Ada", slug: "ada", color: "#aa0000" }),
      b: pixie({ id: "b", name: "Bo", slug: "bo", color: "#00bb00" }),
    };
    const teams = {
      qa: team({ id: "qa", name: "QA crew", handle: "qa", leader_id: "b" }),
      empty: team({ id: "empty", handle: "empty", leader_id: null }),
      gone: team({ id: "gone", handle: "gone", leader_id: "missing" }),
    };
    expect([...mentionLabels(pixies, teams)]).toEqual([
      ["ada", { name: "Ada", color: "#aa0000" }],
      ["bo", { name: "Bo", color: "#00bb00" }],
      ["qa", { name: "QA crew", color: "#00bb00" }],
    ]);
  });
});

describe("leaderColor", () => {
  const pixies = { b: pixie({ id: "b", color: "#00bb00" }) };

  it("is the leader's colour, or none without a known leader", () => {
    expect(leaderColor(team({ leader_id: "b" }), pixies)).toBe("#00bb00");
    expect(leaderColor(team({ leader_id: null }), pixies)).toBeNull();
    expect(leaderColor(team({ leader_id: "missing" }), pixies)).toBeNull();
  });
});
