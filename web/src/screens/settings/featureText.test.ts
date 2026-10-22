import { describe, expect, it } from "vitest";
import { textRuns } from "./featureText.ts";

describe("a feature's text (B103)", () => {
  it("splits backtick spans out as code", () => {
    expect(textRuns("Run `make check` or `make fmt` now.")).toEqual([
      { code: false, text: "Run " },
      { code: true, text: "make check" },
      { code: false, text: " or " },
      { code: true, text: "make fmt" },
      { code: false, text: " now." },
    ]);
  });

  it("keeps text without spans whole, and a span at either end", () => {
    expect(textRuns("Plain words.")).toEqual([{ code: false, text: "Plain words." }]);
    expect(textRuns("`gh` login")).toEqual([
      { code: true, text: "gh" },
      { code: false, text: " login" },
    ]);
  });

  it("leaves a lone or empty pair of backticks as text", () => {
    expect(textRuns("a ` b")).toEqual([{ code: false, text: "a ` b" }]);
    expect(textRuns("a `` b")).toEqual([{ code: false, text: "a `` b" }]);
  });
});
