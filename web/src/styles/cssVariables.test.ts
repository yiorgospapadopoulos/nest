/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// A `var()` naming a property nothing defines makes its whole declaration invalid, so an
// animation or color silently disappears (BUG-84): every one must come from the generated
// tokens, a stylesheet's own declarations, or a component's inline style.
const SHEETS = readdirSync("src/styles")
  .filter((name) => name.endsWith(".css"))
  .map((name) => ({ name, text: readFileSync(`src/styles/${name}`, "utf8") }));

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = `${dir}/${entry.name}`;
    if (entry.isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

function declared(text: string, pattern: RegExp): Set<string> {
  return new Set([...text.matchAll(pattern)].map((m) => m[1] ?? ""));
}

const tokens = declared(readFileSync("src/generated/tokens.css", "utf8"), /(--[\w-]+)\s*:/g);
const inline = declared(
  sources("src")
    .map((path) => readFileSync(path, "utf8"))
    .join("\n"),
  /"(--[\w-]+)"\s*:/g,
);
const local = declared(SHEETS.map((sheet) => sheet.text).join("\n"), /(--[\w-]+)\s*:/g);

function undefinedIn(text: string): string[] {
  const used = [...text.matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1] ?? "");
  return [...new Set(used)].filter(
    (name) => !tokens.has(name) && !local.has(name) && !inline.has(name),
  );
}

describe("CSS custom properties", () => {
  it("are found in the generated tokens", () => {
    expect(tokens.size).toBeGreaterThan(50);
    expect(tokens).toContain("--text-primary");
  });

  it.each(SHEETS)("used in $name are all defined", ({ text }) => {
    expect(undefinedIn(text)).toEqual([]);
  });

  it("would catch a property nothing defines", () => {
    expect(undefinedIn(".x { color: var(--nowhere-defined); }")).toEqual(["--nowhere-defined"]);
  });
});
