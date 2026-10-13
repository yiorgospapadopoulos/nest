import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Plugin } from "vite";
import { appearanceBootScript, themeColorTags, type Colors } from "../src/appearance/boot.ts";

export { themeColorTags, type Colors };

// The installable app's manifest and theme colors, from the design tokens at build time,
// and its icons: the column mark on white, rendered from apple/support/AppIcon-1024.png.

export interface Asset {
  fileName: string;
  source: string | Uint8Array;
}

/** The page colors from the generated token CSS. */
export function tokenColors(css: string): Colors {
  const values = (name: string) =>
    [...css.matchAll(new RegExp(`--${name}:\\s*(?:var\\([^,]+,\\s*)?(#[0-9a-fA-F]{6})`, "g"))]
      .map((m) => m[1])
      .filter((value) => value !== undefined);
  const [light, dark] = values("page-base");
  if (light === undefined || dark === undefined) {
    throw new Error("tokens.css lacks page colors");
  }
  return { light, dark };
}

export const ICON_SIZES = { "icon-192.png": 192, "icon-512.png": 512, "apple-touch-icon.png": 180 };

/** The manifest, plus each icon as `read` returns its file. */
export function pwaAssets(colors: Colors, read: (fileName: string) => Uint8Array): Asset[] {
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
    ...Object.keys(ICON_SIZES).map((fileName) => ({ fileName, source: read(fileName) })),
  ];
}

/**
 * Emits the manifest and icons with the build, and adds the theme colors and the saved
 * appearance (applied before the first paint) to the page.
 */
export function pwa(tokensPath: string, iconsDir: string): Plugin {
  const colors = () => tokenColors(readFileSync(tokensPath, "utf8"));
  return {
    name: "harness-pwa",
    transformIndexHtml(html) {
      return html.replace(
        "<!-- theme-color -->",
        `${themeColorTags(colors())}\n    <script>${appearanceBootScript()}</script>`,
      );
    },
    generateBundle() {
      const read = (fileName: string) => readFileSync(resolve(iconsDir, fileName));
      for (const asset of pwaAssets(colors(), read)) {
        this.emitFile({ type: "asset", fileName: asset.fileName, source: asset.source });
      }
    },
  };
}
