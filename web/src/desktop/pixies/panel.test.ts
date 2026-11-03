import { describe, expect, it } from "vitest";
import { backOf, DETAILS, shownPage, type PixiePage } from "./panel.ts";

describe("the details panel's pages", () => {
  it("goes back from each page to the one it was opened from", () => {
    const pages: [PixiePage, PixiePage, string][] = [
      [{ page: "soul" }, DETAILS, "Details"],
      [{ page: "memory" }, DETAILS, "Details"],
      [{ page: "activity" }, DETAILS, "Details"],
      [{ page: "habits" }, DETAILS, "Details"],
      [{ page: "note", note: "ci" }, { page: "memory" }, "Memory"],
      [{ page: "habit", habit: null }, { page: "habits" }, "Habits"],
      [{ page: "habit", habit: "h1" }, { page: "habits" }, "Habits"],
      [{ page: "history", habit: "h1" }, { page: "habits" }, "Habits"],
    ];
    for (const [page, back, label] of pages) {
      expect(backOf(page)).toEqual({ page: back, label });
    }
    expect(backOf(DETAILS)).toBeNull();
  });

  it("shows the details again once another pixie has the focus", () => {
    const memory = { pixie: "p1", page: { page: "memory" } as PixiePage };
    expect(shownPage(memory, "p1")).toEqual({ page: "memory" });
    expect(shownPage(memory, "p2")).toEqual(DETAILS);
  });
});
