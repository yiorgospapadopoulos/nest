// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The iPhone follows the Mac's look (B102): flat surfaces split by dividers, the Mac's
// colours, the phone's own type sizes from the design tokens, and smaller radii.
const base = readFileSync("src/styles/base.css", "utf8");
const tokens = readFileSync("src/generated/tokens.css", "utf8");

/** The declarations of a selector's own rule in `css`. */
function rule(css: string, selector: string): string {
  const start = css.indexOf(`\n${selector} {`);
  return start === -1 ? "" : css.slice(start, css.indexOf("}", start));
}

/** The value a rule gives a property, or null. */
function value(declarations: string, property: string): string | null {
  const match = new RegExp(`(?:^|[\\s;{])${property}:\\s*([^;]+);`).exec(declarations);
  return match?.[1]?.trim() ?? null;
}

function token(name: string): number {
  const match = new RegExp(`${name}:\\s*([\\d.]+)px;`).exec(tokens);
  return Number(match?.[1]);
}

const root = rule(base, ":root");

describe("the phone's type sizes (B102)", () => {
  // In rem, so they follow the iPhone's text size, at the tokens' sizes on the 17 pt root.
  it.each([
    ["--fs-title", "--typography-size-phone-title"],
    ["--fs-body", "--typography-size-phone-body"],
    ["--fs-meta", "--typography-size-phone-meta"],
    ["--fs-label", "--typography-size-phone-label"],
    ["--fs-micro", "--typography-size-phone-micro"],
  ])("%s matches %s", (alias, name) => {
    const rem = /^([\d.]+)rem$/.exec(value(root, alias) ?? "")?.[1];
    expect(rem, alias).toBeDefined();
    expect(Number(rem) * 17).toBeCloseTo(token(name), 1);
  });
});

describe("the Mac's colours (B102)", () => {
  it("keeps the user's accent for the primary button", () => {
    expect(value(root, "--accent")).toBe("var(--accent-fill)");
    expect(value(rule(base, ".b-pri"), "background")).toBe("var(--accent)");
  });
});

describe("flat surfaces (B102)", () => {
  it("keeps nothing of the removed glass themes and wallpapers (B102)", () => {
    for (const name of ["base.css", "screens.css", "chat.css", "settings.css"]) {
      expect(readFileSync(`src/styles/${name}`, "utf8")).not.toMatch(/glass|wallpaper|\.wall\b/i);
    }
  });
});
