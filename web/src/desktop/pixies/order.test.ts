import { describe, expect, it } from "vitest";
import { pixie, team } from "../../test/fixtures.ts";
import {
  dropsBelow,
  listedPixies,
  listSections,
  movedBy,
  movedOnto,
  neighbors,
  placement,
} from "./order.ts";

// Ported from NestKitTests' PixiesStoreTests and PixieTeamsTests (B40).

const three = ["a", "b", "c"];

describe("pixie order", () => {
  it("moves a pixie onto another, below it going down and above it going up", () => {
    const down = movedOnto(three, "a", "c");
    expect(down).toEqual(["b", "c", "a"]);
    expect(movedOnto(down ?? [], "a", "b")).toEqual(["a", "b", "c"]);
    // Onto itself or an unknown pixie: nothing to send.
    expect(movedOnto(three, "a", "a")).toBeNull();
    expect(movedOnto(three, "x", "a")).toBeNull();
    expect(movedOnto(three, "a", "x")).toBeNull();
  });

  it("moves a pixie up and down among the listed ones of its section only", () => {
    expect(movedBy(three, "b", -1, ["a", "b", "c"])).toEqual(["b", "a", "c"]);
    expect(movedBy(["b", "a", "c"], "b", 1, ["b", "c"])).toEqual(["a", "c", "b"]);
    // Past either end, or a pixie not listed: nothing.
    expect(movedBy(["a", "c", "b"], "b", 1, ["a", "c", "b"])).toBeNull();
    expect(movedBy(["a", "c", "b"], "a", -1, ["a", "c", "b"])).toBeNull();
    expect(movedBy(["a", "c", "b"], "x", 1, ["a", "c", "b"])).toBeNull();
  });

  it("puts a pixie dropped on one in another section into that team, at its place", () => {
    const all = [
      pixie({ id: "a", team_id: null, position: 0 }),
      pixie({ id: "b", team_id: "t1", position: 1 }),
      pixie({ id: "c", team_id: "t1", position: 2 }),
    ];
    expect(placement(all, "a", "c")).toEqual({ team: "t1", order: ["b", "c", "a"] });
    // Within its section it only moves.
    const joined = [
      pixie({ id: "b", team_id: "t1", position: 0 }),
      pixie({ id: "c", team_id: "t1", position: 1 }),
      pixie({ id: "a", team_id: "t1", position: 2 }),
    ];
    expect(placement(joined, "a", "b")).toEqual({ order: ["a", "b", "c"] });
    // Onto a pixie with no team takes it out of its team.
    expect(placement(all, "b", "a")).toEqual({ team: null, order: ["b", "a", "c"] });
    expect(placement(all, "x", "a")).toBeNull();
    expect(placement(all, "a", "x")).toBeNull();
  });

  it("shows the drop line below a pixie dragged down the list, else above", () => {
    const top = pixie({ id: "a", position: 0 });
    const bottom = pixie({ id: "b", position: 3 });
    expect(dropsBelow(top, bottom)).toBe(true);
    expect(dropsBelow(bottom, top)).toBe(false);
  });
});

describe("pixie list sections", () => {
  const list = [
    pixie({ id: "a", team_id: null, position: 0 }),
    pixie({ id: "b", team_id: "t2", position: 1 }),
    pixie({ id: "c", team_id: "t1", position: 2 }),
    pixie({ id: "d", team_id: "t2", position: 3 }),
    pixie({ id: "e", team_id: "gone", position: 4 }),
  ];
  const teams = [
    team({ id: "t2", position: 1, leader_id: "d" }),
    team({ id: "t1", position: 0, leader_id: "c" }),
    team({ id: "t3", position: 2, leader_id: null }),
  ];

  it("lists teams first with their members, then pixies without a team", () => {
    const sections = listSections(list, teams);
    expect(sections.teams.map((s) => s.team.id)).toEqual(["t1", "t2", "t3"]);
    expect(sections.teams.map((s) => s.members.map((p) => p.id))).toEqual([["c"], ["b", "d"], []]);
    // A pixie whose team is not known yet shows without one.
    expect(sections.loose.map((p) => p.id)).toEqual(["a", "e"]);
  });

  it("keeps Move Up and Move Down within the pixie's section", () => {
    const sections = listSections(list, teams);
    expect(neighbors(sections, "d")).toEqual(["b", "d"]);
    expect(neighbors(sections, "e")).toEqual(["a", "e"]);
    expect(neighbors(sections, "zz")).toEqual([]);
  });

  it("lists hidden pixies only while they are shown, in pixie order", () => {
    const pixies = {
      b: pixie({ id: "b", position: 1, hidden: true }),
      a: pixie({ id: "a", position: 0 }),
      c: pixie({ id: "c", position: 2 }),
    };
    expect(listedPixies(pixies, false).map((p) => p.id)).toEqual(["a", "c"]);
    expect(listedPixies(pixies, true).map((p) => p.id)).toEqual(["a", "b", "c"]);
  });
});
