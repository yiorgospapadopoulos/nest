// Wave 7: two panes at the smallest window cut the composer's labels to "Hai…" and "A…".
// A selector without room now leaves the row whole: the context first, then thinking, then
// the permission mode; the model stays.
import { describe, expect, it } from "vitest";
import { itemsToDrop } from "./wholeItems.ts";

const context = { drop: 1, width: 40 };
const thinking = { drop: 2, width: 76 };
const permission = { drop: 3, width: 30 };

describe("the composer's selectors in a narrow pane", () => {
  it("leave the row whole, the least needed first, only as far as needed", () => {
    expect(itemsToDrop(0, [permission, thinking, context], 2)).toEqual(new Set());
    expect(itemsToDrop(30, [permission, thinking, context], 2)).toEqual(new Set([1]));
    expect(itemsToDrop(60, [permission, thinking, context], 2)).toEqual(new Set([1, 2]));
    expect(itemsToDrop(500, [permission, thinking, context], 2)).toEqual(new Set([1, 2, 3]));
  });
});
