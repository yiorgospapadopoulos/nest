import { describe, expect, it } from "vitest";
import { effortLabel, effortOptions } from "./options.ts";

describe("thinking levels", () => {
  it("names the known levels and shows one this app does not know yet as the Mac sends it", () => {
    expect(effortOptions(["xhigh", "turbo"])).toEqual([
      { value: "xhigh", label: "Extra high" },
      { value: "turbo", label: "turbo" },
    ]);
    expect(effortLabel("max")).toBe("Max");
  });
});
