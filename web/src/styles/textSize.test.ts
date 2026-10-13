/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Text follows the iPhone's text size (Dynamic Type): sizes are in rem, and the root takes
// the system body size where the browser knows it.
const SHEETS = ["base.css", "screens.css", "chat.css"].map((name) => ({
  name,
  text: readFileSync(`src/styles/${name}`, "utf8"),
}));

describe("text sizes", () => {
  it.each(SHEETS)("are relative to the root in $name", ({ text }) => {
    // The root's own size is the base the others follow.
    const rules = text.replace(/^html \{[^}]*\}/m, "");
    const fixed = [...rules.matchAll(/font(?:-size)?:[^;]*?\d+(?:\.\d+)?px[^;]*;/g)].map(
      (m) => m[0],
    );
    expect(fixed).toEqual([]);
  });

  it("follow the system text size, keeping 17 points as the base elsewhere", () => {
    const base = SHEETS.find((sheet) => sheet.name === "base.css")?.text ?? "";
    expect(base).toMatch(/html \{[^}]*font-size: 17px;/);
    expect(base).toMatch(
      /@supports \(font: -apple-system-body\) \{\s*html \{\s*font: -apple-system-body;/,
    );
  });
});
