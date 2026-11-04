import { describe, expect, it } from "vitest";
import { codeRef, fileRefsIn, linkRef } from "./fileRefs.ts";

const paths = (text: string) => fileRefsIn(text).map((r) => text.slice(r.start, r.end));

describe("file references", () => {
  it("finds paths in plain text with their line, on real shapes", () => {
    expect(paths("Fixed in web/src/App.tsx:42 and index.html:111.")).toEqual([
      "web/src/App.tsx:42",
      "index.html:111",
    ]);
    expect(paths("See (plans/handoff.md), `x` README.md, or ../a/b.ts:1:2.")).toEqual([
      "plans/handoff.md",
      "README.md",
      "../a/b.ts:1:2",
    ]);
    expect(paths("/Users/me/nest/design/tokens.toml:3-9 and .claude/settings.json")).toEqual([
      "/Users/me/nest/design/tokens.toml:3-9",
      ".claude/settings.json",
    ]);
    expect(fileRefsIn("see a/b.md:12.")[0]?.path).toBe("a/b.md");
  });

  it("leaves URLs, versions, domains and identifiers as text", () => {
    for (const text of [
      "https://example.com/a.md",
      "ssh://host/x/y.md",
      "git@github.com:o/r.git",
      "version 1.2.3 or v2.0.1",
      "example.com and www.example.com/docs/a.md",
      "console.log(a.b) with obj.field and e.g. this",
      "Node.js and Next.js",
      "HTTP/1.1, 1/2.5, TCP/IP, and/or, text/plain",
      "a call: file.py()",
      "src/*.ts and **/x.ts and ~/notes/a.md and $HOME/a.md",
      "web/src/ the folder",
    ]) {
      expect(paths(text), text).toEqual([]);
    }
  });

  it("reads a whole code span as a path, or not at all", () => {
    expect(codeRef("index.html:111")).toBe("index.html");
    expect(codeRef("web/src/App.tsx:42")).toBe("web/src/App.tsx");
    expect(codeRef("app/(shop)/[id]/page.tsx")).toBe("app/(shop)/[id]/page.tsx");
    for (const code of [
      "git diff web/App.tsx",
      "https://a.b/c.md",
      "1.2.3",
      "foo.bar",
      "src/*.ts",
      "a/b",
      "${HOME}/x.md",
    ]) {
      expect(codeRef(code), code).toBeNull();
    }
  });

  it("reads a markdown link with no scheme as a file", () => {
    expect(linkRef("plans/project-plan.md")).toBe("plans/project-plan.md");
    expect(linkRef("./a.ts#L12")).toBe("./a.ts");
    expect(linkRef("web/src/App.tsx:42")).toBe("web/src/App.tsx");
    expect(linkRef("index.html:111")).toBe("index.html");
    expect(linkRef("/Users/me/nest/README.md")).toBe("/Users/me/nest/README.md");
    expect(linkRef("LICENSE")).toBe("LICENSE");
    expect(linkRef("my%20notes/a.md")).toBe("my notes/a.md");
    expect(linkRef("../../etc/passwd")).toBe("../../etc/passwd");
    for (const url of [
      "https://example.com/a.md",
      "file:///etc/passwd",
      "javascript:alert(1)",
      "mailto:me@example.com",
      "#section",
      "//example.com/a.md",
      "example.com",
      "www.example.org/x",
      "docs/",
      "..",
      "%zz",
      "a%0Ab.md",
    ]) {
      expect(linkRef(url), url).toBeNull();
    }
  });
});
