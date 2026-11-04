/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { codeTokens, MAX_COLOURED, type CodeKind } from "./codeColors.ts";

const shown = (language: string, code: string) =>
  codeTokens(language, code).map((t) => [t.kind, code.slice(t.start, t.end)]);

interface Sample {
  language: string;
  code: string;
  tokens: [CodeKind, number, number][];
}

describe("code colours", () => {
  it("keeps a comment marker inside a string a string", () => {
    expect(shown("ts", 'const url = "https://a.b/c"; // real')).toEqual([
      ["keyword", "const"],
      ["string", '"https://a.b/c"'],
      ["comment", "// real"],
    ]);
    expect(shown("python", "x = '# not a comment'  # one")).toEqual([
      ["string", "'# not a comment'"],
      ["comment", "# one"],
    ]);
  });

  it("ends a half-written string with its line, and a half-written block with the code", () => {
    expect(shown("js", 'let a = "open\nlet b')).toEqual([
      ["keyword", "let"],
      ["string", '"open'],
      ["keyword", "let"],
    ]);
    expect(shown("python", 'x = """never closed\nstill')).toEqual([
      ["string", '"""never closed\nstill'],
    ]);
    expect(shown("swift", "/* open")).toEqual([["comment", "/* open"]]);
    expect(shown("js", '"\\')).toEqual([["string", '"\\']]);
    expect(shown("html", '<a href="x')).toEqual([
      ["keyword", "a"],
      ["string", '"x'],
    ]);
  });

  it("leaves a keyword inside an identifier plain", () => {
    expect(shown("go", "format := forEach(iffy, a.for, for_x)")).toEqual([]);
    expect(shown("bash", "./for pre-if --in")).toEqual([]);
  });

  it("colours nothing without a language it knows, or past the size cap", () => {
    expect(codeTokens(null, "const a = 1")).toEqual([]);
    expect(codeTokens("cobol", "const a = 1")).toEqual([]);
    expect(codeTokens("constructor", "const a = 1")).toEqual([]);
    const huge = "const a = 1\n".repeat(MAX_COLOURED / 12 + 1);
    expect(codeTokens("ts", huge)).toEqual([]);
    expect(codeTokens("ts title=x.ts", "const a = 1").length).toBeGreaterThan(0);
  });

  it("stays linear on input made to backtrack", () => {
    const code = "'".repeat(MAX_COLOURED);
    const begun = performance.now();
    for (const language of ["rust", "sql", "html", "bash", "diff"]) {
      codeTokens(language, code);
      codeTokens(language, "<a ".repeat(MAX_COLOURED / 3));
    }
    expect(performance.now() - begun).toBeLessThan(1000);
  });

  it("agrees with the shared sample, which the Mac's tokenizer is held to as well", () => {
    const samples = JSON.parse(
      readFileSync("../design/code-colors-sample.json", "utf8"),
    ) as Sample[];
    expect(samples.length).toBeGreaterThan(30);
    for (const { language, code, tokens } of samples) {
      const found = codeTokens(language, code).map((t) => [t.kind, t.start, t.end]);
      expect(found, language).toEqual(tokens);
    }
  });
});
