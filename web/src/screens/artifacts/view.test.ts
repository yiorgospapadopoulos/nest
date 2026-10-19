import { describe, expect, it } from "vitest";
import { artifact, session } from "../../test/fixtures.ts";
import { KIND_ICONS, KIND_LABELS, chatScopes, originOf, pixieScopes } from "./view.ts";

describe("the history's choices", () => {
  it("are a project chat's, its project's and every project's", () => {
    expect(chatScopes(session({ id: "s1", repo: "cv-page" }))).toEqual([
      { label: "This chat", filter: { session_id: "s1" } },
      { label: "This project", filter: { repo: "cv-page" } },
      { label: "All", filter: {} },
    ]);
  });

  it("are the pixie's in its own chat, as on its page", () => {
    const chat = session({ id: "pc", repo: "pixie:p1", pixie_id: "p1" });
    expect(chatScopes(chat)).toEqual(pixieScopes("p1"));
    expect(pixieScopes("p1")).toEqual([
      { label: "This pixie", filter: { pixie_id: "p1" } },
      { label: "All", filter: {} },
    ]);
  });

  it("start with the run's own in a habit run's chat", () => {
    const run = session({ id: "r1", repo: "pixie:p1", pixie_id: "p1", habit_run_id: "h1" });
    expect(chatScopes(run).map((scope) => scope.label)).toEqual(["This chat", "This pixie", "All"]);
  });
});

describe("where an artifact came from", () => {
  it.each([
    [artifact({ chat_title: "Fix the form" }), "Fix the form"],
    [artifact({ chat_title: null }), "A chat"],
    [artifact({ chat_deleted: true }), "Deleted chat"],
    [artifact({ pixie_id: "p1", pixie_name: "Tester", chat_deleted: true }), "Tester"],
    [artifact({ pixie_id: "p1", pixie_name: null }), "A pixie"],
  ])("%#: %s", (found, expected) => {
    expect(originOf(found)).toBe(expected);
  });
});

describe("the kinds", () => {
  it("each have a label and an icon of their own", () => {
    expect(KIND_LABELS).toEqual({
      markdown: "Markdown",
      html: "HTML",
      slides: "Slides",
      document: "Document",
      design: "Design",
      design_system: "Design system",
    });
    expect(KIND_ICONS).toEqual({
      markdown: "doc",
      html: "code",
      slides: "chart",
      document: "list",
      design: "devices",
      design_system: "contrast",
    });
  });
});
