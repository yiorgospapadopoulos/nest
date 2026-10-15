import { describe, expect, it } from "vitest";
import { outputPreview, PREVIEW_CHARS, PREVIEW_LINES } from "./output.ts";

const lines = (n: number) => Array.from({ length: n }, (_, i) => `line ${String(i + 1)}`);

describe("outputPreview", () => {
  it("shows short output whole", () => {
    expect(outputPreview("one\ntwo\n")).toEqual({ text: "one\ntwo", lines: 2, cut: false });
    expect(outputPreview(lines(PREVIEW_LINES).join("\n"))).toMatchObject({
      lines: PREVIEW_LINES,
      cut: false,
    });
  });

  it("shows the first lines of long output and counts them all", () => {
    const text = lines(3000).join("\n");
    expect(outputPreview(text)).toEqual({
      text: lines(PREVIEW_LINES).join("\n"),
      lines: 3000,
      cut: true,
    });
  });

  it("cuts one very long line by characters", () => {
    const preview = outputPreview("x".repeat(PREVIEW_CHARS * 5));
    expect(preview).toEqual({ text: "x".repeat(PREVIEW_CHARS), lines: 1, cut: true });
  });
});
