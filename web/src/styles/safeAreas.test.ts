/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = ["base.css", "screens.css", "chat.css"]
  .map((name) => readFileSync(`src/styles/${name}`, "utf8"))
  .join("\n");

/** The declarations of a selector's own rule. */
function rule(selector: string): string {
  const start = css.indexOf(`\n${selector} {`);
  return start === -1 ? "" : css.slice(start, css.indexOf("}", start));
}

describe("landscape safe areas", () => {
  it("name the left and right insets", () => {
    expect(rule(":root")).toContain("--sal: env(safe-area-inset-left, 0px);");
    expect(rule(":root")).toContain("--sar: env(safe-area-inset-right, 0px);");
  });

  // The screens, the full-screen chat, the tab bar and the sheets stay clear of the notch.
  it.each([".view", ".push", ".tabbar", ".sheet", ".asheet"])("keep %s inside them", (selector) => {
    const declared = rule(selector);
    expect(declared).toContain("var(--sal)");
    expect(declared).toContain("var(--sar)");
  });
});
