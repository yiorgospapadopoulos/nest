import { readFileSync } from "node:fs";
import type { Plugin } from "vite";
import { encodePng, type Rgb } from "./png.ts";

// The installable app's manifest and icons, generated from the design tokens at build time.

export interface Asset {
  fileName: string;
  source: string | Uint8Array;
}

export interface Colors {
  light: string;
  dark: string;
  // The icon background: the graphite accent.
  mark: string;
}

/** The page colors and the default accent from the generated token CSS. */
export function tokenColors(css: string): Colors {
  const values = (name: string) =>
    [...css.matchAll(new RegExp(`--${name}:\\s*(?:var\\([^,]+,\\s*)?(#[0-9a-fA-F]{6})`, "g"))]
      .map((m) => m[1])
      .filter((value) => value !== undefined);
  const [light, dark] = values("page-base");
  const [mark] = values("accent-fill");
  if (light === undefined || dark === undefined || mark === undefined) {
    throw new Error("tokens.css lacks page or accent colors");
  }
  return { light, dark, mark };
}

function rgb(hex: string): Rgb {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** A white "h" mark on the accent, kept inside the maskable safe zone. */
export function iconPixel(size: number, background: Rgb) {
  const at = (fraction: number) => Math.round(size * fraction);
  const stem = { x0: at(0.32), x1: at(0.44), y0: at(0.24), y1: at(0.76) };
  const arch = { x0: at(0.32), x1: at(0.68), y0: at(0.44), y1: at(0.56) };
  const leg = { x0: at(0.56), x1: at(0.68), y0: at(0.44), y1: at(0.76) };
  const inside = (r: typeof stem, x: number, y: number) =>
    x >= r.x0 && x < r.x1 && y >= r.y0 && y < r.y1;
  return (x: number, y: number): Rgb =>
    inside(stem, x, y) || inside(arch, x, y) || inside(leg, x, y) ? [255, 255, 255] : background;
}

export const ICON_SIZES = { "icon-192.png": 192, "icon-512.png": 512, "apple-touch-icon.png": 180 };

export function pwaAssets(colors: Colors): Asset[] {
  const manifest = {
    name: "harness",
    short_name: "harness",
    description: "Approve, review and steer your coding agents.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: colors.light,
    theme_color: colors.light,
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any maskable" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" },
    ],
  };
  return [
    { fileName: "manifest.webmanifest", source: `${JSON.stringify(manifest, null, 2)}\n` },
    ...Object.entries(ICON_SIZES).map(([fileName, size]) => ({
      fileName,
      source: encodePng(size, iconPixel(size, rgb(colors.mark))),
    })),
  ];
}

export function themeColorTags(colors: Colors): string {
  return [
    `<meta name="theme-color" content="${colors.light}" media="(prefers-color-scheme: light)" />`,
    `<meta name="theme-color" content="${colors.dark}" media="(prefers-color-scheme: dark)" />`,
  ].join("\n    ");
}

/** Emits the manifest and icons with the build, and adds the theme colors to the page. */
export function pwa(tokensPath: string): Plugin {
  const colors = () => tokenColors(readFileSync(tokensPath, "utf8"));
  return {
    name: "harness-pwa",
    transformIndexHtml(html) {
      return html.replace("<!-- theme-color -->", themeColorTags(colors()));
    },
    generateBundle() {
      for (const asset of pwaAssets(colors())) {
        this.emitFile({ type: "asset", fileName: asset.fileName, source: asset.source });
      }
    },
  };
}
