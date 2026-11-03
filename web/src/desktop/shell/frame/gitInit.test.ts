// Init's text goes with the draft it was put in, as on the Mac (Shell.setUpGit), and never
// takes away what the user typed.
import { describe, expect, it } from "vitest";
import { GIT_INIT, initTextLeft } from "./gitInit.ts";

describe("Init's text when its draft closes", () => {
  it("goes with the last draft pane, unless another draft or the user's own text remains", () => {
    expect(initTextLeft("draft:1-1", ["s1", "draft:1-1"], GIT_INIT)).toBe(true);
    expect(initTextLeft("draft:1-1", ["draft:1-1", "draft:2-2"], GIT_INIT)).toBe(false);
    expect(initTextLeft("draft:1-1", ["draft:1-1"], `${GIT_INIT} Also add a README.`)).toBe(false);
    expect(initTextLeft("s1", ["s1"], GIT_INIT)).toBe(false);
  });
});
