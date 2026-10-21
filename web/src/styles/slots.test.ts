/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = ["base.css", "chat.css", "screens.css"]
  .map((name) => readFileSync(`src/styles/${name}`, "utf8"))
  .join("\n");

/** The declarations of a selector's own rule. */
function rule(selector: string): string {
  const start = css.indexOf(`\n${selector} {`);
  return start === -1 ? "" : css.slice(start, css.indexOf("}", start));
}

// Fireflies in a Dot are 12 wide; plain dots in the same lists sit centred in 12 too (B80).
describe("the running mark's slot (B80)", () => {
  it("never squeezes the fireflies into a dot's room", () => {
    expect(css).not.toMatch(/\.ff\s*{[^}]*margin:\s*0 -/);
    expect(rule(".row .ff")).toBe("");
  });

  it("centres a row's 7 px dot in a 12 px slot", () => {
    expect(rule(".row .dot")).toContain("width: 7px;");
    expect(rule(".row .dot")).toContain("margin: 0 2.5px;");
  });

  it("centres the background bar's 8 px summary dot in a 12 px slot", () => {
    expect(rule(".bgsum .dot")).toContain("margin: 0 2px;");
    // The label grows; the dot and the fireflies keep their own width.
    expect(rule(".bgsum span:not(.dot, .ff)")).toContain("flex: 1;");
    expect(rule(".bgsum span:not(.dot)")).toBe("");
  });

  it("gives background task and goal rows a mark column of 12 px or more, centred", () => {
    expect(rule(".bgg li")).toContain("grid-template-columns: 12px 14px");
    expect(rule(".gs-h")).toContain("grid-template-columns: 16px minmax(0, 1fr)");
    const centred = [".bgg li", ".gs-h"].flatMap((p) => [`${p} > .dot`, `${p} > .ff`]);
    expect(rule(centred.join(",\n"))).toContain("justify-self: center;");
  });

  it("keeps the header's still-sprite fireflies spacing to the title only", () => {
    expect(rule(".ch-t h2 .ff")).toContain("margin-right: 8px;");
    expect(rule(".ch-t .ff")).toBe("");
  });
});
