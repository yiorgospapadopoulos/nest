/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The light theme's values in the generated tokens: the first block of each selector.
const CSS = readFileSync("src/generated/tokens.css", "utf8");

function block(selector: string): string {
  const start = CSS.indexOf(`\n${selector} {`);
  if (start < 0) throw new Error(`no ${selector} block`);
  return CSS.slice(start, CSS.indexOf("}", start));
}

type Rgba = [number, number, number, number];

function color(selector: string, name: string): Rgba {
  const value = new RegExp(`--${name}: ([^;]+);`).exec(block(selector))?.[1];
  const hex = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(value ?? "");
  if (hex !== null) return [...hex.slice(1, 4).map((h) => Number.parseInt(h, 16)), 1] as Rgba;
  const rgba = /^rgba\((\d+),(\d+),(\d+),([\d.]+)\)$/.exec(value ?? "");
  if (rgba === null) throw new Error(`--${name} is not a color: ${String(value)}`);
  return rgba.slice(1, 5).map(Number) as Rgba;
}

/** `top` painted over an opaque `bottom`. */
function over(top: Rgba, bottom: Rgba): Rgba {
  const a = top[3];
  return [0, 1, 2].map((i) => (top[i] ?? 0) * a + (bottom[i] ?? 0) * (1 - a)).concat(1) as Rgba;
}

/** WCAG 2 contrast ratio of two opaque colors. */
function contrast(a: Rgba, b: Rgba): number {
  const luminance = (c: Rgba) => {
    const [r, g, bl] = c.slice(0, 3).map((v) => {
      const s = v / 255;
      return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    }) as [number, number, number];
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const WALLPAPERS = ["stone", "sage", "sky", "slate"];
// The glass themes whose light panels are at least as light as the default's.
const THEMES = ["clear", "frosted", "bluegrey"];

describe("tertiary text in the light theme", () => {
  const text = color(":root", "text-tertiary");

  it("reads at 4.5:1 on the page and every wallpaper", () => {
    const grounds = [
      color(":root", "page-base"),
      ...WALLPAPERS.map((w) => color(":root", `wallpaper-${w}-base`)),
    ];
    for (const ground of grounds) {
      expect(contrast(over(text, ground), ground)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(THEMES)("reads at 4.5:1 on the %s glass over every wallpaper", (theme) => {
    const selector = `[data-glass="${theme}"]`;
    for (const wallpaper of WALLPAPERS) {
      const shell = over(
        color(selector, "glass-shell"),
        color(":root", `wallpaper-${wallpaper}-base`),
      );
      for (const layer of ["glass-tint", "glass-surface"]) {
        const ground = over(color(selector, layer), shell);
        for (const g of [shell, ground]) {
          expect(
            contrast(over(text, g), g),
            `${theme} ${layer} ${wallpaper}`,
          ).toBeGreaterThanOrEqual(4.5);
        }
      }
    }
  });
});
