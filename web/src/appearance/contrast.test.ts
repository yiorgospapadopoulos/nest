// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The generated tokens: the light theme in `:root`, the dark theme in its explicit
// `[data-theme="dark"]` block (the media query repeats the same values).
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

const DARK = ':root[data-theme="dark"]';

/** Tertiary text's contrast on an opaque ground. */
function tertiaryOn(root: string, ground: Rgba): number {
  return contrast(over(color(root, "text-tertiary"), ground), ground);
}

describe("tertiary text", () => {
  it("reads at 4.5:1 on the light page", () => {
    expect(tertiaryOn(":root", color(":root", "page-base"))).toBeGreaterThanOrEqual(4.5);
  });

  it("reads at 4.5:1 on the dark page", () => {
    expect(tertiaryOn(DARK, color(DARK, "page-base"))).toBeGreaterThanOrEqual(4.5);
  });
});

describe("Mac palette text", () => {
  // Every layout but the classic phone theme draws its dim text and status words in the
  // Mac palette, over the window, the sidebar, a chat pane or a sheet, bare or on a faint
  // fill (B147). Selected rows use the stronger title colors, so the row fills are left out.
  const TEXT = ["text-secondary", "text-tertiary", "link", "wait", "run", "ok", "bad"];

  it.each([
    ["light", ":root"],
    ["dark", DARK],
  ])("reads at 4.5:1 on every ground in %s", (_name, root) => {
    const window = color(root, "mac-window-opaque");
    const bases = ["mac-side", "mac-chat-pane", "mac-sheet"].map((name) =>
      over(color(root, name), window),
    );
    const grounds = [window, ...bases].flatMap((base) => [
      base,
      ...["mac-soft", "mac-hover", "mac-composer"].map((fill) => over(color(root, fill), base)),
    ]);
    for (const name of TEXT) {
      const ink = color(root, `mac-${name}`);
      for (const ground of grounds) {
        expect(contrast(ink, ground), name).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});

describe("code colours", () => {
  const KINDS = ["comment", "string", "keyword", "number", "added", "removed"];

  it.each([
    ["light", ":root"],
    ["dark", DARK],
  ])("read at 4.5:1 on the code backgrounds in %s", (_name, root) => {
    const window = color(root, "mac-window-opaque");
    const pane = over(color(root, "mac-chat-pane"), window);
    for (const fill of ["mac-soft", "mac-raised"]) {
      const ground = over(color(root, fill), pane);
      for (const kind of KINDS) {
        expect(contrast(color(root, `code-${kind}`), ground), kind).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});
