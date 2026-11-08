import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { defined } from "../test/defined.ts";
import { Markdown } from "./Markdown.tsx";
import { OpenFileContext } from "./openFile.ts";

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
    expect(deep.map((li) => li.className)).toEqual(["d0", "d1"]);
  });

  it("keeps code blocks and rules as written", () => {
    const box = show(
      ["```ts", "const a = **1**;", "", "  indented", "```", "---", "~~~", "never closed"].join(
        "\n",
      ),
    );

    const blocks = [...(box?.children ?? [])];
    expect(blocks.map((b) => b.tagName)).toEqual(["PRE", "HR", "PRE"]);
    expect(blocks[0]?.textContent).toBe("const a = **1**;\n\n  indented");
    expect(blocks[2]?.textContent).toBe("never closed");
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

const cellsOf = (row: Element | undefined) =>
  [...(row?.querySelectorAll("th, td") ?? [])].map((cell) => cell.textContent);

describe("Markdown tables", () => {
  it("draws a table, not a code block, with alignment and inline marks", () => {
    const box = show(
      ["| File | Size | Note |", "|:---|--:|:-:|", "| `a.ts` | 12 | **new** |"].join("\n"),
    );

    expect(box?.querySelector("pre")).toBeNull();
    const rows = screen.getAllByRole("row");
    expect(rows.map(cellsOf)).toEqual([
      ["File", "Size", "Note"],
      ["a.ts", "12", "new"],
    ]);
    const cells = [...(rows[1]?.children ?? [])];
    expect(cells[0]?.querySelector("code")).not.toBeNull();
    expect(cells[1]).toHaveClass("r");
    expect(cells[2]).toHaveClass("c");
    expect(cells[2]?.querySelector("strong")).not.toBeNull();
  });

  it("needs no pipes at the ends of its lines", () => {
    show("a | b\n--- | ---\n1 | 2");

    expect(screen.getAllByRole("row").map(cellsOf)).toEqual([
      ["a", "b"],
      ["1", "2"],
    ]);
  });

  it("keeps escaped pipes and pipes in code inside their cell", () => {
    show(
      [
        "| Command | Why |",
        "|---|---|",
        "| `curl x \\| sh` | a \\| b |",
        "| `grep a|b` | c |",
      ].join("\n"),
    );

    expect(screen.getAllByRole("row").slice(1).map(cellsOf)).toEqual([
      ["curl x | sh", "a | b"],
      ["grep a|b", "c"],
    ]);
  });

  it("pads short rows and drops extra cells", () => {
    show("| a | b |\n|---|---|\n| 1 |\n| 2 | 3 | 4 |");

    expect(screen.getAllByRole("row").slice(1).map(cellsOf)).toEqual([
      ["1", ""],
      ["2", "3"],
    ]);
  });

  it("stays text without a delimiter, or with a malformed one", () => {
    const missing = show("| a | b |\n| 1 | 2 |");
    expect(missing?.querySelector("table, pre")).toBeNull();
    expect(missing?.textContent).toContain("| a | b |");

    const wrongCount = show("| a | b |\n|---|");
    expect(wrongCount?.querySelector("table, pre")).toBeNull();

    const notDashes = show("| a | b |\n|-x-|---|");
    expect(notDashes?.querySelector("table, pre")).toBeNull();

    const pipesOnly = show("Use a | b for this");
    expect(pipesOnly?.querySelector("table, pre")).toBeNull();
  });

  it("starts right after a paragraph and ends at text with no pipes", () => {
    const box = show("Here it is:\n| a |\n|---|\n| 1 |\nThat is all.");

    expect([...(box?.children ?? [])].map((b) => b.className || b.tagName)).toEqual([
      "P",
      "md-tw",
      "P",
    ]);
  });
});

describe("Markdown quotes, tasks and marks", () => {
  it("joins quote lines and reads the marks in them", () => {
    const box = show("> first **bold**\n> second\n\nAfter");

    const quote = box?.querySelector("blockquote");
    expect(quote?.textContent).toBe("first bold second");
    expect(quote?.querySelector("strong")).not.toBeNull();
    expect(screen.getByText("After").closest("blockquote")).toBeNull();
  });

  it("draws task boxes that nobody can tick", () => {
    show("- [ ] open\n- [x] done\n- plain");

    expect(screen.getAllByRole("img").map((box) => box.getAttribute("aria-label"))).toEqual([
      "Not done",
      "Done",
    ]);
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText("open").textContent).toBe("open");
  });

  it("strikes text through", () => {
    show("~~old~~ new");

    expect(screen.getByText("old").tagName).toBe("DEL");
  });

  it("shows escaped marks as their character, but not in code", () => {
    const box = show("\\*not em\\* \\_x\\_ \\[a\\](b) \\# \\| \\` and `\\*code\\*`");

    expect(box?.textContent).toBe("*not em* _x_ [a](b) # | ` and \\*code\\*");
    expect(box?.querySelector("em")).toBeNull();
    expect(screen.getByText(String.raw`\*code\*`).tagName).toBe("CODE");
  });

  it("keeps a heading mark that is escaped as text", () => {
    expect(show(String.raw`\# Not a heading`)?.querySelector("h3")).toBeNull();
  });
});

describe("Markdown web addresses", () => {
  const hrefs = () => screen.getAllByRole("link").map((a) => a.getAttribute("href"));

  it("links a bare address without the punctuation after it", () => {
    const box = show(
      "See https://a.dev/x. Or (https://b.dev/y), https://c.dev/p_(q) and https://d.dev?",
    );

    expect(hrefs()).toEqual([
      "https://a.dev/x",
      "https://b.dev/y",
      "https://c.dev/p_(q)",
      "https://d.dev",
    ]);
    expect(box?.textContent).toBe(
      "See https://a.dev/x. Or (https://b.dev/y), https://c.dev/p_(q) and https://d.dev?",
    );
  });

  it("links an address in angle brackets and shows no brackets", () => {
    const box = show("Open <https://a.dev/x> now");

    expect(hrefs()).toEqual(["https://a.dev/x"]);
    expect(box?.textContent).toBe("Open https://a.dev/x now");
  });

  it("never links anything but http and https, nor a link in a link", () => {
    show("<javascript:alert(1)> ftp://a.dev [https://a.dev](https://b.dev)");

    expect(hrefs()).toEqual(["https://b.dev"]);
    expect(screen.getByRole("link").textContent).toBe("https://a.dev");
  });

  it("shows an image as a link with its words, loading nothing (B136)", () => {
    // Seen in the Linux app on 2026-11-08: ![dot](dot.png) read "!dot".
    const box = show("See ![dot](https://a.dev/dot.png) and ![](https://a.dev/x.png).");

    expect(box?.querySelector("img")).toBeNull();
    expect(box?.textContent).toBe("See dot and https://a.dev/x.png.");
    expect(hrefs()).toEqual(["https://a.dev/dot.png", "https://a.dev/x.png"]);
  });
});

describe("Markdown nesting", () => {
  const depths = (markdown: string) =>
    [...(show(markdown)?.querySelectorAll("li") ?? [])].map((li) => li.className);

  it.each([
    ["3", "1. one\n   - sub\n2. two"],
    ["4", "- one\n    - sub\n- two"],
    ["2", "- one\n  - sub\n- two"],
  ])("takes a %s space sublist as one level deeper", (_, markdown) => {
    expect(depths(markdown)).toEqual(["d0", "d1", "d0"]);
  });

  it("counts each level from the items around it", () => {
    expect(depths("- a\n    - b\n        - c\n    - d\n- e")).toEqual([
      "d0",
      "d1",
      "d2",
      "d1",
      "d0",
    ]);
  });

  it("keeps a code fence under its item, without the item's indent", () => {
    const box = show("1. Install:\n\n   ```sh\n   npm i\n     nested\n   ```\n2. Run");

    const list = box?.querySelectorAll("ul");
    expect(list).toHaveLength(1);
    const items = [...(box?.querySelectorAll("li") ?? [])];
    expect(items).toHaveLength(3);
    expect(items[1]?.querySelector("pre")?.textContent).toBe("npm i\n  nested");
    expect(items[2]?.textContent).toBe("2.Run");
  });

  it("keeps an indented paragraph under its item, in order", () => {
    const box = show("- one\n  - sub\n\n  more on one\n- two\n\nOutside");

    const items = [...(box?.querySelectorAll("li") ?? [])];
    expect(items.map((li) => li.className)).toEqual(["d0", "d1", "d0 more", "d0"]);
    expect(items[2]?.querySelector("p")?.textContent).toBe("more on one");
    expect(screen.getByText("Outside").closest("li")).toBeNull();
  });
});

describe("code blocks", () => {
  it("colours a known language with spans of the same text", () => {
    const code = 'const a = "x"; // note\nreturn 1;';
    const box = show(`\`\`\`ts\n${code}\n\`\`\``);
    const pre = defined(box?.querySelector("pre"));

    expect(pre.textContent).toBe(code);
    expect(pre.querySelector(".code-keyword")?.textContent).toBe("const");
    expect(pre.querySelector(".code-string")?.textContent).toBe('"x"');
    expect(pre.querySelector(".code-comment")?.textContent).toBe("// note");
    expect(pre.innerHTML).not.toContain("<script");
  });

  it("leaves a block without a language plain, and colours a fence still open", () => {
    expect(show("```\nconst a = 1\n```")?.querySelector("pre span")).toBeNull();
    const open = show('```js\nlet a = "half');
    expect(open?.querySelector("pre .code-string")?.textContent).toBe('"half');
  });
});

describe("files a message names", () => {
  const text = "See [the plan](plans/plan.md), `web/src/App.tsx:42` and index.html:111.";

  it("stay text with no way to open them, as on the iPhone", () => {
    const box = show(text);
    expect(box?.querySelector("a")).toBeNull();
    expect(box?.textContent).toBe("See the plan, web/src/App.tsx:42 and index.html:111.");
  });

  it("open by their path where a chat provides that, with their text unchanged", () => {
    const open = vi.fn();
    const box = render(
      <OpenFileContext value={open}>
        <Markdown text={text} />
      </OpenFileContext>,
    ).container;
    const links = [...box.querySelectorAll("a")];
    expect(links.map((a) => a.textContent)).toEqual([
      "the plan",
      "web/src/App.tsx:42",
      "index.html:111",
    ]);
    expect(box.textContent).toBe("See the plan, web/src/App.tsx:42 and index.html:111.");
    expect(links.some((a) => a.hasAttribute("href"))).toBe(false);
    for (const a of links) a.click();
    expect(open.mock.calls.map(([path]) => path as string)).toEqual([
      "plans/plan.md",
      "web/src/App.tsx",
      "index.html",
    ]);
  });

  it("never turn a web or file link into a file, and leave fenced code alone", () => {
    const open = vi.fn();
    const box = render(
      <OpenFileContext value={open}>
        <Markdown
          text={"[web](https://a.b/c.md) [no](file:///etc/passwd)\n\n```\nweb/src/App.tsx\n```"}
        />
      </OpenFileContext>,
    ).container;
    expect(box.querySelectorAll("a.md-file")).toHaveLength(0);
    expect(box.querySelector("a")?.getAttribute("href")).toBe("https://a.b/c.md");
    expect(box.textContent).toContain("no");
  });
});
