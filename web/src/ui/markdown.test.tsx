import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { defined } from "../test/defined.ts";
import { Markdown } from "./Markdown.tsx";

const show = (text: string) => render(<Markdown text={text} />).container.firstElementChild;

describe("Markdown", () => {
  it("renders headings at levels below the card's own", () => {
    show("# One\n## Two ##\n### Three\n#### Four\n###### Six\n#NoSpace");

    expect(screen.getByRole("heading", { name: "One", level: 3 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Two", level: 4 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Three", level: 5 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Four", level: 6 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Six", level: 6 })).toBeInTheDocument();
    expect(screen.getByText("#NoSpace").tagName).toBe("P");
  });

  it("joins wrapped lines into paragraphs and splits them at blank lines", () => {
    const box = show("First line\nsame paragraph\n\n\nSecond\r\nparagraph");

    expect([...(box?.children ?? [])].map((p) => [p.tagName, p.textContent])).toEqual([
      ["P", "First line same paragraph"],
      ["P", "Second paragraph"],
    ]);
  });

  it("lists bullets and numbers with their depth, across blank lines", () => {
    show(
      [
        "Steps:",
        "1. Add zod",
        "   - in package.json",
        "     and the lock file",
        "",
        "2) Validate",
        "* star",
        "+ plus",
        "",
        "After the list",
        "",
        "- Next list",
        "",
        "        - deep",
      ].join("\n"),
    );

    const [steps, next] = screen.getAllByRole("list");
    const items = within(defined(steps)).getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual([
      "1.Add zod",
      "•in package.json and the lock file",
      "2)Validate",
      "•star",
      "•plus",
    ]);
    expect(items.map((li) => li.className)).toEqual(["d0", "d1", "d0", "d0", "d0"]);
    expect(screen.getByText("After the list").tagName).toBe("P");
    const deep = within(defined(next)).getAllByRole("listitem");
    expect(deep.map((li) => li.className)).toEqual(["d0", "d3"]);
  });

  it("keeps code blocks, tables and rules as written", () => {
    const box = show(
      [
        "```ts",
        "const a = **1**;",
        "",
        "  indented",
        "```",
        "| File | Change |",
        "| a.ts | new |",
        "---",
        "~~~",
        "never closed",
      ].join("\n"),
    );

    const blocks = [...(box?.children ?? [])];
    expect(blocks.map((b) => b.tagName)).toEqual(["PRE", "PRE", "HR", "PRE"]);
    expect(blocks[0]?.textContent).toBe("const a = **1**;\n\n  indented");
    expect(blocks[1]?.textContent).toBe("| File | Change |\n| a.ts | new |");
    expect(blocks[3]?.textContent).toBe("never closed");
  });

  it("renders inline code, bold, italic and safe links", () => {
    show(
      "Run `npm test` with **bold _and italic_** and __strong__, *em*, snake_case_name, " +
        "2 * 3 * 4, [docs](https://example.com/a?b=1), [local](javascript:alert) " +
        "and [plain](/relative).",
    );

    expect(screen.getByText("npm test").tagName).toBe("CODE");
    expect(screen.getByText("bold", { exact: false }).tagName).toBe("STRONG");
    expect(screen.getByText("and italic").tagName).toBe("EM");
    expect(screen.getByText("strong").tagName).toBe("STRONG");
    expect(screen.getByText("em").tagName).toBe("EM");
    const link = screen.getByRole("link", { name: "docs" });
    expect(link).toHaveAttribute("href", "https://example.com/a?b=1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getAllByRole("link")).toHaveLength(1);
    const text = screen.getByText(/snake_case_name/).textContent;
    expect(text).toContain("snake_case_name, 2 * 3 * 4,");
    expect(text).toContain("local and plain.");
  });

  it("renders marks at the start and right after each other", () => {
    const box = show("**Start**`next` end");

    expect(box?.firstElementChild?.innerHTML).toBe("<strong>Start</strong><code>next</code> end");
  });

  it("renders nothing for an empty plan", () => {
    expect(show("")?.childElementCount).toBe(0);
  });
});
