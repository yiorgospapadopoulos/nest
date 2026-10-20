// @vitest-environment node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { ICON_SIZES, pwa, pwaAssets, themeColorTags, tokenColors } from "./pwa.ts";

const TOKENS = resolve(import.meta.dirname, "../src/generated/tokens.css");
const ICONS = resolve(import.meta.dirname, "icons");
const colors = { light: "#eeeeec", dark: "#0c0c0d" };

/** Width and height from a PNG's IHDR chunk. */
function pngSize(png: Uint8Array): [number, number] {
  const buffer = Buffer.from(png);
  expect([...buffer.subarray(0, 8)]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  expect(buffer.toString("ascii", 12, 16)).toBe("IHDR");
  return [buffer.readUInt32BE(16), buffer.readUInt32BE(20)];
}

describe("pwa assets", () => {
  it("reads the page colors from the generated tokens", () => {
    expect(tokenColors(readFileSync(TOKENS, "utf8"))).toEqual(colors);
    expect(() => tokenColors(":root {}")).toThrow("tokens.css lacks page colors");
  });

  it("ships the pixie icon at every size the manifest and iOS ask for", () => {
    for (const [fileName, size] of Object.entries(ICON_SIZES)) {
      expect(pngSize(readFileSync(resolve(ICONS, fileName)))).toEqual([size, size]);
    }
  });

  it("builds a standalone manifest and takes the icons as they are", () => {
    const read = vi.fn((fileName: string) => new TextEncoder().encode(fileName));
    const assets = pwaAssets(colors, read);
    const manifest = JSON.parse(assets[0]?.source as string) as Record<string, unknown>;

    expect(assets.map((a) => a.fileName)).toEqual([
      "manifest.webmanifest",
      "icon-192.png",
      "icon-512.png",
      "apple-touch-icon.png",
    ]);
    expect(new TextDecoder().decode(assets[2]?.source as Uint8Array)).toBe("icon-512.png");
    expect(manifest).toMatchObject({
      name: "Nest",
      display: "standalone",
      theme_color: "#eeeeec",
      icons: [
        { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any maskable" },
        { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" },
      ],
    });
    expect(themeColorTags(colors)).toContain(
      'content="#0c0c0d" media="(prefers-color-scheme: dark)"',
    );
  });

  it("emits the assets and adds theme colors to the page", () => {
    const plugin = pwa(TOKENS, ICONS);
    const emitFile = vi.fn();
    const html = (plugin.transformIndexHtml as (html: string) => string)(
      "<head><!-- theme-color --></head>",
    );
    (plugin.generateBundle as (this: unknown) => void).call({ emitFile });

    expect(html).toContain('<meta name="theme-color" content="#eeeeec"');
    expect(html).toContain("<script>(function () {\n  try {\n    var raw =\n");
    expect(emitFile).toHaveBeenCalledTimes(4);
    expect(emitFile).toHaveBeenCalledWith({
      type: "asset",
      fileName: "apple-touch-icon.png",
      source: readFileSync(resolve(ICONS, "apple-touch-icon.png")),
    });
  });
});
