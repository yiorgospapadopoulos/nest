import { describe, expect, it } from "vitest";
import { choicesWith } from "./pixieChoices.ts";

describe("pixie choices", () => {
  it("keep a value set elsewhere, in order", () => {
    expect(choicesWith([1, 2, 3], 2)).toEqual([1, 2, 3]);
    expect(choicesWith([1, 2, 5], 4)).toEqual([1, 2, 4, 5]);
    expect(choicesWith([1, 2], null)).toEqual([1, 2]);
  });
});
