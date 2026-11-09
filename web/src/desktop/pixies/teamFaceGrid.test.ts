// @vitest-environment node
/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Regression (B157, Ubuntu 26.04): a team's row in a chat's sidebar tree read "w @crew".
// Its mark's class had no rule, so the four sprites stood in one row across the team's
// name. Layout cannot be measured in jsdom, so this guards that every class a team mark
// is given lays the sprites out two by two.

function files(dir: string, ending: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return files(path, ending);
    return entry.name.endsWith(ending) ? [path] : [];
  });
}

const root = "src/desktop";
const css = files(root, ".css")
  .map((path) => readFileSync(path, "utf8"))
  .join("\n");
const classes = files(root, ".tsx").flatMap((path) =>
  [...readFileSync(path, "utf8").matchAll(/<TeamFace[^>]*?className="([^"]+)"/gs)].map(
    (match) => match[1] ?? "",
  ),
);

/** The declarations of a selector's own rule. */
function rule(selector: string): string {
  const start = css.indexOf(`\n${selector} {`);
  return start === -1 ? "" : css.slice(start, css.indexOf("}", start));
}

describe("a team's mark", () => {
  it("is found where the desktop app shows one", () => {
    expect(classes).toContain("fr-team");
  });

  it("lays its members out two by two wherever it is shown", () => {
    for (const name of classes) {
      const declared = rule(`.${name}`);
      expect(declared, name).toContain("display: inline-grid;");
      expect(declared, name).toContain("grid-template-columns: repeat(2, auto);");
    }
  });
});
