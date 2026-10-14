import { describe, expect, it } from "vitest";
import { pixie, team } from "../test/fixtures.ts";
import { mentionColors, mentionParts } from "./mentions.ts";

describe("mentionParts", () => {
  const colors = new Map([
    ["tester", "#111111"],
    ["qa", "#222222"],
  ]);

  it("marks whole @ tokens that name a known pixie or team", () => {
    expect(mentionParts("@tester check, then @qa.\n@nobody", colors)).toEqual([
      { text: "@tester", color: "#111111" },
      { text: " check, then ", color: null },
      { text: "@qa", color: "#222222" },
      { text: ".\n@nobody", color: null },
    ]);
  });

  it("leaves tokens inside words or running on plain", () => {
    expect(mentionParts("me@tester @tester-2 @testers @tester_x @Tester", colors)).toEqual([
      { text: "me@tester @tester-2 @testers @tester_x @Tester", color: null },
    ]);
    expect(mentionParts("", colors)).toEqual([]);
  });
});

describe("mentionColors", () => {
  it("colours slugs by their pixie and handles by their leader", () => {
    const pixies = {
      a: pixie({ id: "a", slug: "ada", color: "#aa0000" }),
      b: pixie({ id: "b", slug: "bo", color: "#00bb00" }),
    };
    const teams = {
      qa: team({ id: "qa", handle: "qa", leader_id: "b" }),
      empty: team({ id: "empty", handle: "empty", leader_id: null }),
      gone: team({ id: "gone", handle: "gone", leader_id: "missing" }),
    };
    expect([...mentionColors(pixies, teams)]).toEqual([
      ["ada", "#aa0000"],
      ["bo", "#00bb00"],
      ["qa", "#00bb00"],
    ]);
  });
});
