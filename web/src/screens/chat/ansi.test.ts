import { describe, expect, it } from "vitest";
import { ansiSpans } from "./ansi.ts";

const ESC = "\x1b";

describe("ansiSpans", () => {
  it("keeps plain text as one plain span", () => {
    expect(ansiSpans("> vite\n  ready\n")).toEqual([
      { text: "> vite\n  ready\n", color: null, bold: false },
    ]);
  });

  it("has nothing for empty output", () => {
    expect(ansiSpans("")).toEqual([]);
  });

  it("colours text with the basic and bright colours until a reset", () => {
    expect(ansiSpans(`${ESC}[32mVITE${ESC}[0m ready ${ESC}[91merror${ESC}[39m done`)).toEqual([
      { text: "VITE", color: 32, bold: false },
      { text: " ready ", color: null, bold: false },
      { text: "error", color: 91, bold: false },
      { text: " done", color: null, bold: false },
    ]);
  });

  it("makes text bold until a reset or normal weight, keeping its colour", () => {
    expect(
      ansiSpans(`${ESC}[1m412${ESC}[22m ms ${ESC}[1;36mLocal${ESC}[m plain ${ESC}[1mB${ESC}[0mC`),
    ).toEqual([
      { text: "412", color: null, bold: true },
      { text: " ms ", color: null, bold: false },
      { text: "Local", color: 36, bold: true },
      { text: " plain ", color: null, bold: false },
      { text: "B", color: null, bold: true },
      { text: "C", color: null, bold: false },
    ]);
  });

  it("ignores codes outside the basic colours, skipping 256 and true colours whole", () => {
    expect(
      ansiSpans(
        `${ESC}[4;38m${ESC}[38;5;31ma${ESC}[48;2;1;2;3;33mb${ESC}[40;100mc${ESC}[29;38;5;1;98m`,
      ),
    ).toEqual([
      { text: "a", color: null, bold: false },
      { text: "bc", color: 33, bold: false },
    ]);
  });

  it("joins text that escapes split without changing its style", () => {
    expect(ansiSpans(`${ESC}[31mone${ESC}[31m two`)).toEqual([
      { text: "one two", color: 31, bold: false },
    ]);
  });

  it("drops other escapes: cursor moves, clears, titles, two byte ones", () => {
    const raw = `${ESC}[2K${ESC}[1Ga${ESC}[?25lb${ESC}]0;title${ESC}7c${ESC}]8;;x${ESC}\\d${ESC}`;
    expect(ansiSpans(raw)).toEqual([{ text: "abcd", color: null, bold: false }]);
  });

  it("drops a sequence the output stopped in the middle of", () => {
    expect(ansiSpans(`ready${ESC}[3`)).toEqual([{ text: "ready", color: null, bold: false }]);
  });

  it("drops control characters but keeps tabs", () => {
    expect(ansiSpans("a\x07\tb\x08")).toEqual([{ text: "a\tb", color: null, bold: false }]);
  });

  it("shows a line redrawn with carriage returns at its latest, and CRLF as a newline", () => {
    expect(ansiSpans("10%\r50%\r100%\r\nnext\r\n")).toEqual([
      { text: "100%\nnext\n", color: null, bold: false },
    ]);
  });
});
