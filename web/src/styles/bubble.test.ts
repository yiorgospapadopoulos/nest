// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = ["base.css", "chat.css"]
  .map((name) => readFileSync(`src/styles/${name}`, "utf8"))
  .join("\n");

/** The declarations of a selector's own rule. */
function rule(selector: string): string {
  const start = css.indexOf(`\n${selector} {`);
  return start === -1 ? "" : css.slice(start, css.indexOf("}", start));
}

describe("the user's message bubble (B80)", () => {
  it("is the solid accent with the accent's on colour by default", () => {
    expect(rule(".m-u")).toContain("background: var(--bubble);");
    expect(rule(".m-u")).toContain("color: var(--on-bubble);");
    expect(rule(":root")).toContain("--bubble: var(--accent);");
    expect(rule(":root")).toContain("--on-bubble: var(--on-accent);");
  });

  it("keeps the neutral choice", () => {
    expect(rule(':root[data-bubble="neutral"]')).toContain(
      "--bubble: var(--surface-neutral-bubble);",
    );
  });
});

describe("selected text in your own message", () => {
  // The desktop's general `html.desk ::selection` used to outrank it, so the highlight
  // never showed in the Mac and Linux chat.
  it("outranks the desktop's general selection colour", () => {
    expect(css).toContain(":root .dc-ubub::selection,");
    expect(css).toContain(":root .m-u::selection,");
    expect(rule(":root .dc-ubub *::selection")).toContain("background: var(--mac-text-highlight);");
  });
});
