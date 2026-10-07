// @vitest-environment node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { inflateSync } from "node:zlib";
import { describe, expect, it, vi } from "vitest";
import { defined } from "../src/test/defined.ts";
import { crc32, encodePng } from "./png.ts";
import { iconPixel, pwa, pwaAssets, themeColorTags, tokenColors } from "./pwa.ts";

const TOKENS = resolve(import.meta.dirname, "../src/generated/tokens.css");
const colors = { light: "#eeeeec", dark: "#0c0c0d", mark: "#2b2b2e" };

function chunks(png: Uint8Array) {
  const buffer = Buffer.from(png);
  const found: { type: string; data: Buffer }[] = [];
  for (let at = 8; at < buffer.length;) {
    const length = buffer.readUInt32BE(at);
    found.push({
      type: buffer.toString("ascii", at + 4, at + 8),
      data: buffer.subarray(at + 8, at + 8 + length),
    });
    at += 12 + length;
  }
  return found;
}

describe("png", () => {
  it("computes the standard CRC-32", () => {
    expect(crc32(new TextEncoder().encode("123456789"))).toBe(0xcbf43926);
  });

  it("writes a valid RGB image with filtered rows", () => {
    const png = encodePng(2, (x, y) => [x * 100, y * 100, 7]);

    expect([...png.subarray(0, 8)]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    const [header, data, end] = chunks(png);
    expect(header?.type).toBe("IHDR");
    expect(header?.data.readUInt32BE(0)).toBe(2);
    expect(end?.type).toBe("IEND");
    expect([...inflateSync(defined(data).data)]).toEqual([
      0, 0, 0, 7, 100, 0, 7, 0, 0, 100, 7, 100, 100, 7,
    ]);
  });
});

describe("pwa assets", () => {
  it("reads page and accent colors from the generated tokens", () => {
    expect(tokenColors(readFileSync(TOKENS, "utf8"))).toEqual(colors);
    expect(() => tokenColors(":root {}")).toThrow("tokens.css lacks page or accent colors");
  });

  it("draws a white mark inside the icon's safe zone", () => {
    const pixel = iconPixel(100, [1, 2, 3]);

    expect(pixel(0, 0)).toEqual([1, 2, 3]);
    expect(pixel(35, 30)).toEqual([255, 255, 255]);
    expect(pixel(50, 50)).toEqual([255, 255, 255]);
    expect(pixel(60, 70)).toEqual([255, 255, 255]);
    expect(pixel(50, 70)).toEqual([1, 2, 3]);
  });

  it("builds a standalone manifest and the icons", () => {
    const assets = pwaAssets(colors);
    const manifest = JSON.parse(assets[0]?.source as string) as Record<string, unknown>;

    expect(assets.map((a) => a.fileName)).toEqual([
      "manifest.webmanifest",
      "icon-192.png",
      "icon-512.png",
      "apple-touch-icon.png",
    ]);
    expect(manifest).toMatchObject({
      name: "harness",
      display: "standalone",
      theme_color: "#eeeeec",
    });
    expect(themeColorTags(colors)).toContain(
      'content="#0c0c0d" media="(prefers-color-scheme: dark)"',
    );
  });

  it("emits the assets and adds theme colors to the page", () => {
    const plugin = pwa(TOKENS);
    const emitFile = vi.fn();
    const html = (plugin.transformIndexHtml as (html: string) => string)(
      "<head><!-- theme-color --></head>",
    );
    (plugin.generateBundle as (this: unknown) => void).call({ emitFile });

    expect(html).toContain('<meta name="theme-color" content="#eeeeec"');
    expect(emitFile).toHaveBeenCalledTimes(4);
    expect(emitFile).toHaveBeenCalledWith(
      expect.objectContaining({ type: "asset", fileName: "manifest.webmanifest" }),
    );
  });
});
