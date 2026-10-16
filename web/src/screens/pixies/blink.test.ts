import { describe, expect, it } from "vitest";
import type { Mascot } from "../../api/types.ts";
import { blinkOf, BLINKS } from "./blink.ts";

describe("which cells a mascot blinks (B48)", () => {
  // The topmost of each grid's small enclosed holes, as [x, y], row by row; the robot has
  // none, so its lone eye cells go out instead.
  const expected: Record<Mascot, ReturnType<typeof blinkOf>> = {
    invader: {
      mode: "fill",
      cells: [
        [4, 3],
        [7, 3],
      ],
    },
    ghost: {
      mode: "fill",
      cells: [
        [4, 3],
        [7, 3],
        [4, 4],
        [7, 4],
      ],
    },
    cat: {
      mode: "fill",
      cells: [
        [4, 5],
        [7, 5],
      ],
    },
    // Two rings of five: (3,3) (4,3) (3,4) (3,5) (4,5) and its mirror.
    owl: {
      mode: "fill",
      cells: [
        [3, 3],
        [4, 3],
        [7, 3],
        [8, 3],
        [3, 4],
        [8, 4],
        [3, 5],
        [4, 5],
        [7, 5],
        [8, 5],
      ],
    },
    robot: {
      mode: "hide",
      cells: [
        [4, 4],
        [7, 4],
      ],
    },
    frog: {
      mode: "fill",
      cells: [
        [3, 3],
        [8, 3],
      ],
    },
    mushroom: {
      mode: "fill",
      cells: [
        [5, 2],
        [6, 2],
      ],
    },
    bunny: {
      mode: "fill",
      cells: [
        [3, 6],
        [8, 6],
      ],
    },
    crab: {
      mode: "fill",
      cells: [
        [4, 4],
        [7, 4],
      ],
    },
    sprout: {
      mode: "fill",
      cells: [
        [4, 7],
        [7, 7],
      ],
    },
  };

  it.each(Object.keys(expected) as Mascot[])("pins the %s's cells", (mascot) => {
    expect(BLINKS[mascot]).toEqual(expected[mascot]);
  });

  it("takes holes of up to six cells, and only those starting on the topmost row", () => {
    const rows = ["########", "#..#...#", "#..#####", "###.#.##", "########"];
    // Four and three cells from row 1; the single cells lower down are left out.
    expect(blinkOf(rows)).toEqual({
      mode: "fill",
      cells: [
        [1, 1],
        [2, 1],
        [4, 1],
        [5, 1],
        [6, 1],
        [1, 2],
        [2, 2],
      ],
    });
    expect(blinkOf(["#####", "#...#", "#...#", "#####"]).cells).toHaveLength(6);
    expect(blinkOf(["#####", "#...#", "#...#", "#..##", "#####"])).toEqual({
      mode: "hide",
      cells: [],
    });
  });

  it("leaves out holes larger than six cells and those open to the border", () => {
    const rows = ["#######", "#...#.#", "#.#.###", "#...#..", "#######"];
    // The ring of eight is too big; the hole at the right edge is open; one cell is left.
    expect(blinkOf(rows)).toEqual({ mode: "fill", cells: [[5, 1]] });
  });

  it("hides lone filled cells when there is no hole, and nothing when there are none", () => {
    expect(blinkOf(["#..", "...", "..#"])).toEqual({
      mode: "hide",
      cells: [
        [0, 0],
        [2, 2],
      ],
    });
    expect(blinkOf(["##", ".."])).toEqual({ mode: "hide", cells: [] });
  });
});
