// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// B116 item 6: a long action sheet (the model list) ran off the top of the screen, its
// first entries out of reach, because `.asheet` had no height limit and `.asg` hid its
// overflow. Layout cannot be measured in jsdom, so this guards the rules that bound the
// sheet to the safe area and let its choices scroll, and that `ui/Sheet.tsx` puts `asl`
// on every action sheet's group of choices.

const css = readFileSync("src/styles/chat.css", "utf8");
const sheet = readFileSync("src/ui/Sheet.tsx", "utf8");

/** The declarations of a selector's own rule. */
function rule(selector: string): string {
  const start = css.indexOf(`\n${selector} {`);
  return start === -1 ? "" : css.slice(start, css.indexOf("}", start));
}

describe("action sheets", () => {
  it("are never taller than the screen inside its safe areas", () => {
    const declared = rule(".asheet");
    expect(declared).toContain("flex-direction: column;");
    expect(declared).toMatch(/max-height: calc\(100% - var\(--sat\) - var\(--sab\)/);
  });

  it("scroll their choices, which may shrink, while Cancel keeps its size", () => {
    const choices = rule(".asheet > .asg.asl");
    expect(choices).toContain("min-height: 0;");
    expect(choices).toContain("overflow-y: auto;");
    expect(choices).toMatch(/flex: 0 1 auto;/);
    expect(rule(".asheet > .asg")).toContain("flex: none;");
    expect(sheet).toContain('className="asg asl"');
  });
});
