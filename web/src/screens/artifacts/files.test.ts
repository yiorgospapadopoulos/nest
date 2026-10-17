import { afterEach, describe, expect, it, vi } from "vitest";
import { fileName, saveFile } from "./files.ts";

describe("fileName", () => {
  it.each([
    ["Options compared", "markdown", "Options compared.md"],
    ["Report", "html", "Report.html"],
    ['a/b\\c:d*e?f"g<h>i|j', "markdown", "a b c d e f g h i j.md"],
    ["  spaced \n\t out  ", "markdown", "spaced out.md"],
    ["...hidden", "html", "hidden.html"],
    ["/// ", "markdown", "Artifact.md"],
    ["bell\u0007 and \u007fdel", "markdown", "bell and del.md"],
  ] as const)("%j as %s is %j", (title, kind, expected) => {
    expect(fileName(title, kind)).toBe(expected);
  });

  it("keeps a long title to 100 characters", () => {
    expect(fileName("x".repeat(300), "markdown")).toBe(`${"x".repeat(100)}.md`);
  });
});

describe("saveFile", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("downloads the raw content under the file name, then frees it", async () => {
    vi.useFakeTimers();
    const blobs: Blob[] = [];
    const create = vi.fn((blob: Blob) => {
      blobs.push(blob);
      return "blob:x";
    });
    const revoke = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    const clicked: HTMLAnchorElement[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push(this);
    });

    saveFile("Report: Q4", "html", "<p>Hi</p>");

    expect(clicked).toHaveLength(1);
    expect(clicked[0]?.download).toBe("Report Q4.html");
    expect(clicked[0]?.href).toBe("blob:x");
    expect(clicked[0]?.isConnected).toBe(false);
    expect(blobs[0]?.type).toBe("text/html;charset=utf-8");
    expect(await blobs[0]?.text()).toBe("<p>Hi</p>");
    expect(revoke).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(revoke).toHaveBeenCalledWith("blob:x");
    vi.unstubAllGlobals();
  });
});
