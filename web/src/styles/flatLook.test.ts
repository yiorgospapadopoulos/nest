/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The iPhone follows the Mac's look (B102): flat surfaces split by dividers, the Mac's
// colours, the phone's own type sizes from the design tokens, and smaller radii.
const base = readFileSync("src/styles/base.css", "utf8");
const screens = readFileSync("src/styles/screens.css", "utf8");
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
// The flat panels, radii and spacing, in their own `:root` rule after the first.
const panels = rule(base.slice(base.indexOf("/* Panels")), ":root");

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

  it("sets the body text in the phone's body size", () => {
    expect(value(rule(base, "body"), "font")).toBe("var(--fs-body)/1.35 var(--sf)");
  });

  it("names the row height and the card radius from the tokens", () => {
    expect(value(root, "--row")).toBe("var(--spacing-phone-row)");
    expect(value(root, "--r-phone")).toBe("var(--radius-phone-card)");
    expect(token("--spacing-phone-row")).toBe(44);
  });
});

describe("the Mac's colours (B102)", () => {
  it.each([
    ["--bg", "var(--mac-window-opaque)"],
    ["--t1", "var(--mac-text-primary)"],
    ["--t2", "var(--mac-text-secondary)"],
    ["--t3", "var(--mac-text-tertiary)"],
    ["--hair", "var(--mac-divider)"],
    ["--hair2", "var(--mac-raised)"],
    ["--fill", "var(--mac-soft)"],
    ["--fill2", "var(--mac-raised)"],
    ["--div", "var(--mac-divider)"],
    ["--side", "var(--mac-side)"],
    ["--soft", "var(--mac-soft)"],
    ["--raised", "var(--mac-raised)"],
    ["--composer", "var(--mac-composer)"],
    ["--sel", "var(--mac-selection)"],
    ["--sheet", "var(--mac-sheet)"],
    ["--wait", "var(--mac-wait)"],
    ["--run", "var(--mac-run)"],
    ["--ok", "var(--mac-ok)"],
    ["--bad", "var(--mac-bad)"],
    ["--link", "var(--mac-link)"],
    ["--scan", "var(--mac-scanline)"],
  ])("%s is %s", (alias, expected) => {
    expect(value(root, alias)).toBe(expected);
  });

  it("keeps the user's accent for the primary button", () => {
    expect(value(root, "--accent")).toBe("var(--accent-fill)");
    expect(value(rule(base, ".b-pri"), "background")).toBe("var(--accent)");
  });
});

describe("flat surfaces (B102)", () => {
  it("draws flat panels: no blur, border or shadow", () => {
    const gl = rule(base, ".gl");
    expect(value(gl, "background")).toBe("var(--bg)");
    expect(gl).not.toMatch(/backdrop-filter|box-shadow|border:/);
    expect(value(panels, "--gfilter")).toBe("none");
    expect(value(panels, "--gl-sh")).toBe("none");
    expect(value(panels, "--g1")).toBe("var(--bg)");
    expect(value(panels, "--g2")).toBe("var(--mac-sheet)");
    expect(value(panels, "--g-brd")).toBe("var(--mac-divider)");
  });

  it("keeps nothing of the removed glass themes and wallpapers (B102)", () => {
    for (const name of ["base.css", "screens.css", "chat.css", "settings.css"]) {
      expect(readFileSync(`src/styles/${name}`, "utf8")).not.toMatch(/glass|wallpaper|\.wall\b/i);
    }
  });

  it("keeps the transcript's spacing", () => {
    expect(value(panels, "--tr-pad-top")).toBe("14px");
    expect(value(panels, "--tr-pad-x")).toBe("16px");
    expect(value(panels, "--tr-pad-bottom")).toBe("10px");
    expect(value(panels, "--tr-gap")).toBe("11px");
  });

  it("uses the Mac's radii", () => {
    expect(value(panels, "--r-sheet")).toBe("var(--radius-mac-sheet)");
    for (const alias of ["--r-big", "--r-card", "--r-pane"]) {
      expect(value(panels, alias)).toBe("var(--radius-phone-card)");
    }
    for (const alias of ["--r-inner", "--r-tab", "--r-item", "--r-ctl"]) {
      expect(value(panels, alias)).toBe("var(--radius-mac-row)");
    }
    expect(value(panels, "--r-sm")).toBe("var(--radius-mac-button)");
    expect(value(panels, "--r-ctl-lg")).toBe("var(--radius-phone-card)");
  });
});

describe("status dots (B102 item 1)", () => {
  it("draws idle as an outline, as the Mac's StatusDot", () => {
    const idle = rule(base, ".dot.s-idle");
    expect(value(idle, "background")).toBe("transparent");
    expect(value(idle, "box-shadow")).toBe("inset 0 0 0 1.3px var(--t3)");
  });

  it("are 7 points, as on the Mac", () => {
    const dot = rule(base, ".dot");
    expect(value(dot, "width")).toBe("7px");
    expect(value(dot, "height")).toBe("7px");
  });
});

describe("the tab bar (B102 items 17, 18)", () => {
  it("is a flat bar along the bottom with a divider on top", () => {
    const bar = rule(screens, ".tabbar");
    expect(value(bar, "left")).toBe("0");
    expect(value(bar, "right")).toBe("0");
    expect(value(bar, "bottom")).toBe("0");
    expect(value(bar, "border-top")).toBe("1px solid var(--div)");
    expect(value(bar, "background")).toBe("linear-gradient(var(--side), var(--side)), var(--bg)");
    expect(bar).not.toMatch(/border-radius|box-shadow|backdrop-filter/);
  });

  it("marks the chosen tab by its colour, not a filled pill", () => {
    expect(value(rule(screens, ".tb"), "color")).toBe("var(--t2)");
    const chosen = rule(screens, '.tb[aria-selected="true"]');
    expect(value(chosen, "color")).toBe("var(--t1)");
    expect(chosen).not.toMatch(/background/);
  });

  it("shows the Needs you count as a quiet coloured number", () => {
    const count = rule(screens, ".tb .cnt");
    expect(value(count, "color")).toBe("var(--wait)");
    expect(count).not.toMatch(/background|border-radius/);
    expect(rule(screens, ".tb .badge")).toBe("");
  });
});
