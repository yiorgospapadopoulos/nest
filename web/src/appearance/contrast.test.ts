/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The generated tokens: the light theme in `:root` and `[data-glass]`, the dark theme in
// its explicit `[data-theme="dark"]` blocks (the media query repeats the same values).
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
const STOPS = [1, 2, 3];
const DARK = ':root[data-theme="dark"]';
const darkGlass = (theme: string) =>
  `${DARK}[data-glass="${theme}"], ${DARK} [data-glass="${theme}"]`;

/** Tertiary text's contrast on an opaque ground. */
function tertiaryOn(root: string, ground: Rgba): number {
  return contrast(over(color(root, "text-tertiary"), ground), ground);
}

/** The theme's window shell over each wallpaper, and its panels over that. */
function glassGrounds(root: string, glass: string): [string, Rgba][] {
  return WALLPAPERS.flatMap((wallpaper) => {
    const shell = over(color(glass, "glass-shell"), color(root, `wallpaper-${wallpaper}-base`));
    return [
      [`${wallpaper} shell`, shell],
      ...["glass-tint", "glass-surface"].map(
        (layer) => [`${wallpaper} ${layer}`, over(color(glass, layer), shell)] as [string, Rgba],
      ),
    ];
  });
}

describe("tertiary text in the light theme", () => {
  // The glass themes whose light panels are at least as light as the default's. Smoke and
  // Deep give 3.88, a known exception.
  const themes = ["clear", "frosted", "bluegrey"];

  it("reads at 4.5:1 on the page and every wallpaper", () => {
    const grounds = [
      color(":root", "page-base"),
      ...WALLPAPERS.map((w) => color(":root", `wallpaper-${w}-base`)),
    ];
    for (const ground of grounds) {
      expect(tertiaryOn(":root", ground)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(themes)("reads at 4.5:1 on the %s glass over every wallpaper", (theme) => {
    for (const [where, ground] of glassGrounds(":root", `[data-glass="${theme}"]`)) {
      expect(tertiaryOn(":root", ground), `${theme} ${where}`).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe("tertiary text in the dark theme", () => {
  it("reads at 4.5:1 on the page and every wallpaper", () => {
    const grounds = [
      color(DARK, "page-base"),
      ...WALLPAPERS.map((w) => color(DARK, `wallpaper-${w}-base`)),
    ];
    for (const ground of grounds) {
      expect(tertiaryOn(DARK, ground)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(["clear", "frosted", "bluegrey", "smoke", "deep"])(
    "reads at 4.5:1 on the %s glass over every wallpaper",
    (theme) => {
      for (const [where, ground] of glassGrounds(DARK, darkGlass(theme))) {
        expect(tertiaryOn(DARK, ground), `${theme} ${where}`).toBeGreaterThanOrEqual(4.5);
      }
    },
  );
});

describe("tertiary text directly over the wallpapers' glows", () => {
  // Where a glow peaks, these stops fall short of 4.5:1. Reaching it would take tertiary
  // text as dark as secondary in light mode, or a visible change to the wallpapers: an open
  // decision (BUG-72). Each floor is today's ratio, rounded down, so the gap cannot quietly grow.
  const SHORT: Record<string, number> = {
    "light stone stop 1": 4.28,
    "light stone stop 3": 4.04,
    "light sage stop 1": 4.25,
    "light sage stop 3": 3.95,
    "light sky stop 1": 4.32,
    "light sky stop 3": 4.1,
    "light slate stop 1": 4.14,
    "light slate stop 2": 4.41,
    "light slate stop 3": 3.75,
    "dark stone stop 3": 4.03,
    "dark sage stop 3": 3.91,
    "dark sky stop 3": 4,
    "dark slate stop 3": 4.11,
  };
  const ratios = [
    ["light", ":root"],
    ["dark", DARK],
  ].flatMap(([mode, root]) =>
    WALLPAPERS.flatMap((wallpaper) =>
      STOPS.map((stop) => {
        const ground = color(String(root), `wallpaper-${wallpaper}-stop-${String(stop)}`);
        return [
          `${String(mode)} ${wallpaper} stop ${String(stop)}`,
          tertiaryOn(String(root), ground),
        ];
      }),
    ),
  ) as [string, number][];

  it("reads at 4.5:1 on every other stop", () => {
    for (const [stop, ratio] of ratios) {
      if (!(stop in SHORT)) expect(ratio, stop).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("stays at least at today's ratio where it falls short, and the list stays current", () => {
    for (const [stop, ratio] of ratios) {
      const floor = SHORT[stop];
      if (floor === undefined) continue;
      expect(ratio, stop).toBeGreaterThanOrEqual(floor);
      expect(ratio, `${stop} now reaches 4.5:1; take it off the list`).toBeLessThan(4.5);
    }
  });
});
